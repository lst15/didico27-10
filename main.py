"""Entry point for executing the login request workflow."""

from __future__ import annotations

from collections.abc import Mapping
import csv
import json
from pathlib import Path
import re
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qsl, urlencode

from app import DEFAULT_LOGIN_REQUEST, DEFAULT_OFFLINE_REQUEST, LoginClient, ServiceRequest


BASE_DIR = Path(__file__).resolve().parent
SEARCH_VALUES_FILE = BASE_DIR / "search_values.txt"
OUTPUT_DIR = BASE_DIR / "saida"
OUTPUT_FILE = OUTPUT_DIR / "dados.csv"
OUTPUT_BANKS_DIR = OUTPUT_DIR / "bancos"
BANKS_FILE = BASE_DIR / "bancos.txt"


def main() -> None:
    """Execute the configured login request and print its outcome."""

    client = LoginClient()
    login_response = client.authenticate(DEFAULT_LOGIN_REQUEST)
    print(login_response.status_code)
    print(login_response.body)

    for search_value in _load_search_values(SEARCH_VALUES_FILE):
        offline_request = _build_offline_request(DEFAULT_OFFLINE_REQUEST, search_value)
        response = client.perform_authenticated(offline_request)
        print(f"Busca realizada: {search_value}")
        print(response.status_code)
        print(response.body)

        nb_identifier = _extract_nb_identifier(response.body)
        if nb_identifier is None:
            continue

        benefit_request = _build_benefit_request(
            DEFAULT_OFFLINE_REQUEST, nb_identifier
        )
        benefit_response = client.perform_authenticated(benefit_request)
        print(f"Requisição por benefício realizada com NB: {nb_identifier}")
        print(benefit_response.status_code)
        hidden_inputs = _extract_hidden_inputs(benefit_response.body)
        print(json.dumps(hidden_inputs, ensure_ascii=False))
        _append_hidden_inputs_to_csv(hidden_inputs, OUTPUT_FILE)


def _load_search_values(path: Path) -> Iterable[str]:
    """Yield non-empty search values from the provided text file."""

    if not path.exists():
        raise FileNotFoundError(
            f"O arquivo com os valores de busca não foi encontrado: {path}"
        )

    with path.open(encoding="utf-8") as values_file:
        for line in values_file:
            value = line.strip()
            if value:
                yield value


def _build_offline_request(
    base_request: ServiceRequest, search_value: str
) -> ServiceRequest:
    """Create a new offline request by replacing the search value in the payload."""

    payload = _override_payload_fields(base_request.payload, {"busca": search_value})
    return ServiceRequest(
        url=base_request.url,
        headers=base_request.headers,
        payload=payload,
    )


def _build_benefit_request(
    base_request: ServiceRequest, nb_identifier: str
) -> ServiceRequest:
    """Create a new request targeting benefit lookups using the NB identifier."""

    payload = _override_payload_fields(
        base_request.payload,
        {"selectBC": "beneficio", "busca": f"{nb_identifier} "},
    )
    return ServiceRequest(
        url=base_request.url,
        headers=base_request.headers,
        payload=payload,
    )


def _override_payload_fields(
    payload: Mapping[str, str] | str, overrides: Mapping[str, str]
) -> Mapping[str, str] | str:
    """Return ``payload`` with the provided form fields replaced."""

    if isinstance(payload, str):
        pairs = parse_qsl(payload, keep_blank_values=True)
        updated_pairs = []
        seen_keys: set[str] = set()
        for key, value in pairs:
            if key in overrides:
                updated_pairs.append((key, overrides[key]))
                seen_keys.add(key)
            else:
                updated_pairs.append((key, value))
        for key, value in overrides.items():
            if key not in seen_keys:
                updated_pairs.append((key, value))
        return urlencode(updated_pairs, doseq=True)

    if isinstance(payload, Mapping):
        updated_payload = dict(payload)
        updated_payload.update(overrides)
        return updated_payload

    raise TypeError(
        "Tipo de payload não suportado para substituição dinâmica de campos."
    )


def _extract_nb_identifier(response_body: Mapping[str, object] | str) -> str | None:
    """Retrieve the NB identifier from the service response, if present."""

    if not isinstance(response_body, Mapping):
        return None

    nb_values = response_body.get("nb")
    if not isinstance(nb_values, list):
        return None

    candidate = None
    if len(nb_values) > 1 and isinstance(nb_values[1], str):
        candidate = nb_values[1]
    else:
        for value in nb_values:
            if isinstance(value, str) and value.strip():
                candidate = value
                break

    if not candidate:
        return None

    candidate = candidate.strip()
    if not candidate:
        return None

    return candidate.split()[0]


class _HiddenInputParser(HTMLParser):
    """Parse hidden inputs and ``phone_with_ddd`` spans from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.hidden_inputs: dict[str, str] = {}
        self.phones: list[str] = []
        self._phone_depth = 0
        self._current_phone_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): (value or "") for name, value in attrs}
        if tag == "input":
            input_type = attrs_dict.get("type", "").lower()
            if input_type == "hidden":
                name = attrs_dict.get("name")
                if name:
                    self.hidden_inputs[name] = attrs_dict.get("value", "")
            return

        if tag == "span":
            classes = attrs_dict.get("class", "")
            class_names = {cls.lower() for cls in classes.split() if cls}
            if "phone_with_ddd" in class_names:
                if self._phone_depth == 0:
                    self._current_phone_parts = []
                self._phone_depth += 1
                return

        if self._phone_depth and tag == "br":
            self._current_phone_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "span" and self._phone_depth:
            self._phone_depth -= 1
            if self._phone_depth == 0:
                phone = "".join(self._current_phone_parts)
                phone = unescape(phone)
                phone = " ".join(phone.split())
                if phone:
                    self.phones.append(phone)
                self._current_phone_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._phone_depth:
            self._current_phone_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._phone_depth:
            self._current_phone_parts.append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if self._phone_depth:
            self._current_phone_parts.append(unescape(f"&#{name};"))

def _extract_hidden_inputs(
    response_body: Mapping[str, object] | str,
) -> dict[str, object]:
    """Return hidden input fields mapped as name/value pairs from an HTML response."""

    html: str | None
    if isinstance(response_body, Mapping):
        html_candidate = response_body.get("html")
        html = html_candidate if isinstance(html_candidate, str) else None
    elif isinstance(response_body, str):
        html = response_body
    else:
        html = None

    if html is None:
        return {"phones": []}

    parser = _HiddenInputParser()
    parser.feed(html)
    parser.close()

    result: dict[str, object] = dict(parser.hidden_inputs)
    result["phones"] = parser.phones
    return result


def _append_hidden_inputs_to_csv(
    hidden_inputs: Mapping[str, object], output_file: Path
) -> None:
    """Persist hidden input data to ``output_file`` in CSV format."""

    processed_row = {
        key: _stringify_csv_value(value) for key, value in hidden_inputs.items()
    }

    _write_csv_row_with_dynamic_schema(processed_row, output_file)

    bank_code = processed_row.get("banco_codigo", "").strip()
    if bank_code:
        bank_name = _lookup_bank_name(bank_code)
        bank_filename = _sanitize_bank_filename(bank_name) if bank_name else bank_code
        bank_output_file = OUTPUT_BANKS_DIR / f"{bank_filename}.csv"
        _write_csv_row_with_dynamic_schema(processed_row, bank_output_file)


def _lookup_bank_name(bank_code: str) -> str | None:
    """Return the bank name associated with ``bank_code`` using ``BANKS_FILE``."""

    normalized_code = bank_code.zfill(3)

    try:
        bank_mapping = _load_bank_mapping()
    except OSError:
        return None

    return bank_mapping.get(normalized_code) or bank_mapping.get(bank_code)


@lru_cache(maxsize=1)
def _load_bank_mapping() -> dict[str, str]:
    """Load the bank code/name mapping from ``BANKS_FILE``."""

    mapping: dict[str, str] = {}

    if not BANKS_FILE.exists():
        return mapping

    with BANKS_FILE.open(encoding="utf-8") as banks_file:
        for line in banks_file:
            code, name = _parse_bank_line(line)
            if code and name:
                mapping[code] = name

    return mapping


def _parse_bank_line(line: str) -> tuple[str | None, str | None]:
    """Extract the bank ``code`` and ``name`` from a raw ``line``."""

    raw_line = line.strip()
    if not raw_line or raw_line.startswith("#"):
        return None, None

    # Try common separators first.
    for separator in (";", ",", " - ", "-", "\t"):
        if separator in raw_line:
            code, name = raw_line.split(separator, 1)
            return _clean_bank_code(code), name.strip() or None

    parts = raw_line.split(None, 1)
    if len(parts) == 2:
        return _clean_bank_code(parts[0]), parts[1].strip() or None

    return None, None


def _clean_bank_code(code: str) -> str | None:
    """Normalize ``code`` ensuring it contains only digits."""

    digits = re.sub(r"\D", "", code)
    return digits.zfill(3) if digits else None


def _sanitize_bank_filename(bank_name: str) -> str:
    """Return a filesystem-friendly filename derived from ``bank_name``."""

    sanitized = re.sub(r"[^\w]+", "_", bank_name, flags=re.UNICODE)
    sanitized = sanitized.strip("_")
    return sanitized or "banco"


def _write_csv_row_with_dynamic_schema(
    row_data: Mapping[str, str], output_file: Path
) -> None:
    """Append ``row_data`` to ``output_file`` ensuring schema compatibility."""

    output_dir = output_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    output_exists = output_file.exists() and output_file.stat().st_size > 0
    if output_exists:
        with output_file.open("r", encoding="utf-8", newline="") as existing_file:
            reader = csv.reader(existing_file, delimiter=";")
            try:
                existing_header = next(reader)
            except StopIteration:
                existing_header = []
        existing_fields = existing_header
    else:
        existing_fields = []

    processed_fields = sorted(row_data.keys())

    if existing_fields:
        existing_field_set = set(existing_fields)
        new_fields = set(processed_fields) - existing_field_set
    else:
        existing_field_set = set()
        new_fields = set()

    if new_fields:
        # Merge existing data with the new schema and rewrite the CSV file.
        merged_fields = sorted(existing_field_set | set(processed_fields))
        with output_file.open("r", encoding="utf-8", newline="") as existing_file:
            reader = csv.DictReader(existing_file, delimiter=";")
            existing_rows = list(reader)

        with output_file.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=merged_fields, delimiter=";", extrasaction="ignore"
            )
            writer.writeheader()
            for existing_row in existing_rows:
                writer.writerow(
                    {field: existing_row.get(field, "") for field in merged_fields}
                )
            writer.writerow({field: row_data.get(field, "") for field in merged_fields})
        return

    fieldnames = existing_fields if existing_fields else processed_fields
    write_header = not existing_fields

    with output_file.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=fieldnames, delimiter=";", extrasaction="ignore"
        )
        if write_header:
            writer.writeheader()
        writer.writerow({field: row_data.get(field, "") for field in fieldnames})


def _stringify_csv_value(value: object) -> str:
    """Convert ``value`` into a string suitable for CSV serialization."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)

    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


if __name__ == "__main__":
    main()
