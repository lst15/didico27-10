"""Entry point for executing the login request workflow."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence as ABCSequence
import csv
import json
from pathlib import Path
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode

from app import DEFAULT_LOGIN_REQUEST, DEFAULT_OFFLINE_REQUEST, LoginClient, ServiceRequest


BASE_DIR = Path(__file__).resolve().parent
SEARCH_VALUES_FILE = BASE_DIR / "search_values.txt"
OUTPUT_DIR = BASE_DIR / "saida"
OUTPUT_FILE = OUTPUT_DIR / "dados.txt"
OUTPUT_BANKS_DIR = OUTPUT_DIR / "bancos"
BANKS_FILE = BASE_DIR / "bancos.txt"


def main(argv: Sequence[str] | None = None) -> None:
    """Execute the configured login request and print its outcome."""

    args = _parse_arguments(argv)

    client = LoginClient()
    login_response = client.authenticate(DEFAULT_LOGIN_REQUEST)
    print(login_response.status_code)
    print(login_response.body)

    search_values = list(_load_search_values(SEARCH_VALUES_FILE))
    if not search_values:
        return

    semaphore = threading.Semaphore(args.threads)
    file_lock = threading.Lock()

    threads: list[threading.Thread] = []
    for search_value in search_values:
        thread = threading.Thread(
            target=_run_search_workflow,
            args=(search_value, client, semaphore, file_lock),
            name=f"cpf-search-{search_value}",
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Return the parsed command-line arguments for the script."""

    parser = argparse.ArgumentParser(
        description=(
            "Executa consultas utilizando a sessão autenticada e controla o número "
            "máximo de execuções concorrentes com threads."
        )
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Número máximo de execuções simultâneas após o login. Deve ser um "
            "inteiro positivo."
        ),
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.threads < 1:
        parser.error("o parâmetro --threads deve ser um inteiro positivo")
    return args


def _run_search_workflow(
    search_value: str,
    client: LoginClient,
    semaphore: threading.Semaphore,
    file_lock: threading.Lock,
) -> None:
    """Execute the workflow for a single ``search_value`` using ``client``."""

    hidden_inputs: Mapping[str, object] | None = None

    try:
        with semaphore:
            offline_request = _build_offline_request(
                DEFAULT_OFFLINE_REQUEST, search_value
            )
            response = client.perform_authenticated(offline_request)
            print(f"Busca realizada: {search_value}")
            print(response.status_code)
            print(response.body)

            bank_records = _extract_bank_consultation_records(response.body)
            if bank_records:
                with file_lock:
                    _persist_bank_consultations(bank_records)

            nb_identifier = _extract_nb_identifier(response.body)
            if nb_identifier is None:
                return

            benefit_request = _build_benefit_request(
                DEFAULT_OFFLINE_REQUEST, nb_identifier
            )
            benefit_response = client.perform_authenticated(benefit_request)
            print(f"Requisição por benefício realizada com NB: {nb_identifier}")
            print(benefit_response.status_code)
            hidden_inputs = _extract_hidden_inputs(benefit_response.body)
            print(json.dumps(hidden_inputs, ensure_ascii=False))
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"Erro ao processar {search_value}: {exc}")
        return

    if hidden_inputs is not None:
        with file_lock:
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
    """Persist hidden input data to ``output_file`` in pipe-delimited text format."""

    processed_row = {
        key: _stringify_csv_value(value) for key, value in hidden_inputs.items()
    }

    _write_csv_row_with_dynamic_schema(processed_row, output_file)



@dataclass(frozen=True)
class _BankConsultationRecord:
    """Container for data grouped by bank returned in a consultation."""

    label: str
    person_entries: list[object]
    numbers: list[str]
    raw_data: Mapping[str, object]


def _extract_bank_consultation_records(
    response_body: Mapping[str, object] | str,
) -> list[_BankConsultationRecord]:
    """Return bank records present in the consultation ``response_body``."""

    if not isinstance(response_body, Mapping):
        return []

    records: list[_BankConsultationRecord] = []
    for candidate in _iter_bank_candidates(response_body):
        label = _coerce_bank_label(candidate)
        if not label:
            continue

        person_entries = _collect_person_entries(candidate)
        numbers = _collect_number_entries(candidate)

        records.append(
            _BankConsultationRecord(
                label=label,
                person_entries=person_entries,
                numbers=numbers,
                raw_data=dict(candidate),
            )
        )

    return records


def _persist_bank_consultations(records: Sequence[_BankConsultationRecord]) -> None:
    """Create per-bank folders and append consultation data to the expected files."""

    OUTPUT_BANKS_DIR.mkdir(parents=True, exist_ok=True)

    for record in records:
        bank_dir_name = record.label.strip()
        if not bank_dir_name:
            continue

        bank_dir = OUTPUT_BANKS_DIR / bank_dir_name
        bank_dir.mkdir(parents=True, exist_ok=True)

        dados_file = bank_dir / "dados.txt"
        numeros_file = bank_dir / "numeros.txt"

        entries = record.person_entries or [record.raw_data]

        with dados_file.open("a", encoding="utf-8") as dados:
            for entry in entries:
                serialized = _serialize_person_entry(entry)
                if serialized:
                    dados.write(serialized)
                    dados.write("\n")

        with numeros_file.open("a", encoding="utf-8") as numeros:
            for number in record.numbers:
                numeros.write(f"{number}\n")


def _serialize_person_entry(entry: object) -> str:
    """Serialize a consultation entry for storage in ``dados.txt``."""

    if entry is None:
        return ""

    if isinstance(entry, str):
        return entry.strip()

    try:
        return json.dumps(entry, ensure_ascii=False, default=str)
    except TypeError:
        return str(entry)


def _iter_bank_candidates(obj: object) -> Iterable[Mapping[str, object]]:
    """Yield mappings that appear to represent banks in the response payload."""

    if isinstance(obj, Mapping):
        if _looks_like_bank_candidate(obj):
            yield obj
        for value in obj.values():
            yield from _iter_bank_candidates(value)
        return

    if isinstance(obj, ABCSequence) and not isinstance(obj, (str, bytes, bytearray)):
        for item in obj:
            yield from _iter_bank_candidates(item)


def _looks_like_bank_candidate(candidate: Mapping[str, object]) -> bool:
    """Determine whether ``candidate`` likely corresponds to a bank entry."""

    label = candidate.get("label")
    if not isinstance(label, str) or not label.strip():
        return False

    if any(
        key in candidate
        for key in ("value", "codigo", "code", "bank", "banco", "bank_code")
    ):
        return True

    return any("numero" in key.lower() for key in candidate.keys())


def _coerce_bank_label(candidate: Mapping[str, object]) -> str | None:
    """Return the label for ``candidate`` or ``None`` if unavailable."""

    label = candidate.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()

    bank_code = _extract_bank_code(candidate)
    if bank_code:
        bank_name = _lookup_bank_name(bank_code)
        if bank_name:
            return bank_name
        return bank_code
    return None


def _extract_bank_code(candidate: Mapping[str, object]) -> str | None:
    """Extract a bank code from ``candidate`` when available."""

    for key in ("value", "codigo", "code", "bank_code", "banco"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _collect_person_entries(candidate: Mapping[str, object]) -> list[object]:
    """Collect person data associated with a bank entry."""

    entries: list[object] = []
    for key, value in candidate.items():
        lowered = key.lower()
        if any(token in lowered for token in ("pessoa", "beneficiario", "titular", "cliente")):
            entries.extend(_normalize_person_value(value))
        elif "dados" in lowered:
            normalized = _normalize_person_value(value)
            if normalized:
                entries.extend(normalized)
        elif isinstance(value, Mapping) or (
            isinstance(value, ABCSequence) and not isinstance(value, (str, bytes, bytearray))
        ):
            entries.extend(_collect_person_entries(value))
    return entries


def _normalize_person_value(value: object) -> list[object]:
    """Normalize person-related values into a list of serializable entries."""

    if isinstance(value, Mapping):
        return [dict(value)]

    if isinstance(value, ABCSequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized: list[object] = []
        for item in value:
            if isinstance(item, Mapping):
                normalized.append(dict(item))
        return normalized

    return []


def _collect_number_entries(candidate: Mapping[str, object]) -> list[str]:
    """Collect number values related to the consultation bank entry."""

    numbers: list[str] = []
    seen: set[str] = set()

    for number in _extract_numbers_from_object(candidate):
        normalized = number.strip()
        if normalized and normalized not in seen:
            numbers.append(normalized)
            seen.add(normalized)

    return numbers


def _extract_numbers_from_object(obj: object) -> Iterable[str]:
    """Yield numeric strings from ``obj`` based on contextual keys."""

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            lowered = key.lower()
            if any(token in lowered for token in ("numero", "número", "nb")):
                yield from _flatten_numbers(value)
            elif isinstance(value, Mapping) or (
                isinstance(value, ABCSequence) and not isinstance(value, (str, bytes, bytearray))
            ):
                yield from _extract_numbers_from_object(value)
    elif isinstance(obj, ABCSequence) and not isinstance(obj, (str, bytes, bytearray)):
        for item in obj:
            yield from _extract_numbers_from_object(item)


def _flatten_numbers(value: object) -> Iterable[str]:
    """Return an iterable of stringified numbers from ``value``."""

    if isinstance(value, str):
        yield value
        return

    if isinstance(value, (int, float)):
        yield str(value)
        return

    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _flatten_numbers(nested)
        return

    if isinstance(value, ABCSequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _flatten_numbers(item)


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

    if not BANKS_FILE.exists():
        return {}

    try:
        content = BANKS_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}

    content = content.strip()
    if not content:
        return {}

    json_mapping = _try_parse_bank_json(content)
    if json_mapping:
        return json_mapping

    mapping: dict[str, str] = {}
    for line in content.splitlines():
        code, name = _parse_bank_line(line)
        if code and name:
            mapping[code] = name

    return mapping


def _try_parse_bank_json(content: str) -> dict[str, str]:
    """Attempt to parse ``content`` as JSON bank mappings."""

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    mapping: dict[str, str] = {}

    def _consume(obj: object) -> None:
        if isinstance(obj, list):
            for item in obj:
                _consume(item)
            return

        if isinstance(obj, Mapping):
            code = obj.get("value") or obj.get("code")
            name = obj.get("label") or obj.get("name")
            if isinstance(code, str) and isinstance(name, str):
                normalized_code = _clean_bank_code(code)
                if normalized_code and name.strip():
                    mapping[normalized_code] = name.strip()
            for value in obj.values():
                _consume(value)

    _consume(data)
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


def _write_csv_row_with_dynamic_schema(
    row_data: Mapping[str, str], output_file: Path
) -> None:
    """Append ``row_data`` to ``output_file`` ensuring schema compatibility."""

    output_dir = output_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    output_exists = output_file.exists() and output_file.stat().st_size > 0
    if output_exists:
        with output_file.open("r", encoding="utf-8", newline="") as existing_file:
            reader = csv.reader(existing_file, delimiter="|")
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
        # Merge existing data with the new schema and rewrite the output file.
        merged_fields = sorted(existing_field_set | set(processed_fields))
        with output_file.open("r", encoding="utf-8", newline="") as existing_file:
            reader = csv.DictReader(existing_file, delimiter="|")
            existing_rows = list(reader)

        with output_file.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=merged_fields, delimiter="|", extrasaction="ignore"
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
            csv_file, fieldnames=fieldnames, delimiter="|", extrasaction="ignore"
        )
        if write_header:
            writer.writeheader()
        writer.writerow({field: row_data.get(field, "") for field in fieldnames})


def _stringify_csv_value(value: object) -> str:
    """Convert ``value`` into a string suitable for pipe-delimited serialization."""

    if value is None:
        return ""

    if isinstance(value, str):
        return _normalize_whitespace(value)

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (list, tuple, set)):
        return ", ".join(
            _normalize_whitespace(str(item))
            if isinstance(item, str)
            else str(item)
            for item in value
        )

    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def _normalize_whitespace(value: str) -> str:
    """Collapse consecutive whitespace characters in ``value`` into single spaces."""

    normalized = re.sub(r"\s+", " ", value, flags=re.UNICODE)
    return normalized.strip()


if __name__ == "__main__":
    main()
