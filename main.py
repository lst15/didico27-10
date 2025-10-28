"""Entry point for executing the login request workflow.

When executed directly without command-line parameters, this module now
displays a minimal graphical interface that allows the operator to choose the
desired number of threads before starting the workflow.
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from tkinter import messagebox
from collections.abc import Mapping
import csv
import json
from pathlib import Path
import re
import threading
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

_PREFERRED_DADOS_FIELDS = (
    "cpf",
    "nome",
    "data_nascimento",
    "beneficio",
    "banco_agencia",
    "banco_conta",
)


def main(argv: Sequence[str] | None = None) -> None:
    """Execute the configured login request and print its outcome."""

    args = _parse_arguments(argv)
    _run_workflow(args.threads)


def _run_workflow(max_threads: int) -> None:
    """Execute the login workflow limiting concurrency to ``max_threads``."""

    client = LoginClient()
    login_response = client.authenticate(DEFAULT_LOGIN_REQUEST)
    print(login_response.status_code)
    print(login_response.body)

    search_values = list(_load_search_values(SEARCH_VALUES_FILE))
    if not search_values:
        return

    semaphore = threading.Semaphore(max_threads)
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


def _launch_interface() -> None:
    """Display a basic GUI to configure and start the workflow."""

    root = tk.Tk()
    root.title("Configurar Execução")
    root.resizable(False, False)

    selected_threads: dict[str, int | None] = {"value": None}

    frame = tk.Frame(root, padx=16, pady=16)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text="Quantidade de threads:",
        anchor="w",
    ).pack(fill=tk.X)

    threads_var = tk.StringVar(value="1")
    threads_spinbox = tk.Spinbox(
        frame,
        from_=1,
        to=999,
        textvariable=threads_var,
        width=10,
        justify="center",
    )
    threads_spinbox.pack(pady=(4, 12))

    def on_start() -> None:
        try:
            threads = int(threads_var.get())
            if threads < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Valor inválido",
                "Informe um número inteiro positivo de threads.",
                parent=root,
            )
            return

        selected_threads["value"] = threads
        root.quit()

    start_button = tk.Button(frame, text="Inicializar", command=on_start)
    start_button.pack(fill=tk.X)

    root.mainloop()
    root.destroy()

    threads_value = selected_threads["value"]
    if threads_value is not None:
        _run_workflow(threads_value)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _launch_interface()
    else:
        main()


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

    bank_code = processed_row.get("banco_codigo", "").strip()
    if bank_code:
        bank_label = _lookup_bank_name(bank_code)
        if bank_label:
            bank_directory = _ensure_bank_directory(bank_label)
            _append_bank_data(bank_directory, processed_row)
            bank_numbers = _extract_bank_numbers(hidden_inputs)
            if bank_numbers:
                _append_bank_numbers(bank_directory, bank_numbers)


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
    existing_rows: list[dict[str, str]] = []
    existing_fields: list[str] = []

    if output_exists:
        with output_file.open("r", encoding="utf-8", newline="") as existing_file:
            reader = csv.DictReader(existing_file, delimiter="|")
            existing_fields = reader.fieldnames or []
            existing_rows = list(reader)

    target_fields = _order_dados_fields(existing_fields, row_data.keys())
    needs_rewrite = (not output_exists) or (existing_fields != target_fields)

    if needs_rewrite:
        with output_file.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=target_fields, delimiter="|", extrasaction="ignore"
            )
            writer.writeheader()
            for existing_row in existing_rows:
                writer.writerow({field: existing_row.get(field, "") for field in target_fields})
            writer.writerow({field: row_data.get(field, "") for field in target_fields})
        return

    with output_file.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=existing_fields, delimiter="|", extrasaction="ignore"
        )
        writer.writerow({field: row_data.get(field, "") for field in existing_fields})


def _order_dados_fields(
    existing_fields: Sequence[str], new_fields: Iterable[str]
) -> list[str]:
    """Return the desired ``dados.txt`` field order combining existing and new fields."""

    combined_fields = set(existing_fields) | set(new_fields)
    ordered_fields: list[str] = []

    for field in _PREFERRED_DADOS_FIELDS:
        if field in combined_fields:
            ordered_fields.append(field)

    remaining_fields = sorted(combined_fields - set(ordered_fields))
    ordered_fields.extend(remaining_fields)
    return ordered_fields


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


def _ensure_bank_directory(bank_label: str) -> Path:
    """Create (if needed) and return the directory assigned to ``bank_label``."""

    normalized_label = bank_label.strip()
    if not normalized_label:
        raise ValueError("bank_label must not be empty")

    safe_label = normalized_label.replace("/", "-")
    bank_directory = OUTPUT_BANKS_DIR / safe_label
    bank_directory.mkdir(parents=True, exist_ok=True)
    return bank_directory


def _append_bank_data(bank_directory: Path, row_data: Mapping[str, str]) -> None:
    """Append ``row_data`` to ``dados.txt`` using pipe-delimited format."""

    bank_data_file = bank_directory / "dados.txt"
    _write_csv_row_with_dynamic_schema(row_data, bank_data_file)


def _extract_bank_numbers(hidden_inputs: Mapping[str, object]) -> list[str]:
    """Return a list of number strings extracted from ``hidden_inputs``."""

    numbers: list[str] = []
    raw_numbers = hidden_inputs.get("phones")

    def _collect(value: object) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                numbers.append(stripped)
            return
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for item in value:
                _collect(item)

    _collect(raw_numbers)
    return numbers


def _append_bank_numbers(bank_directory: Path, numbers: Sequence[str]) -> None:
    """Append ``numbers`` to the ``numeros.txt`` file, one per line."""

    numbers_file = bank_directory / "numeros.txt"
    fixed_numbers_file = bank_directory / "numeros_fixos.txt"

    fixed_numbers: list[str] = []

    with numbers_file.open("a", encoding="utf-8") as output:
        for number in numbers:
            output.write(f"{number}\n")
            if _is_fixed_line_number(number):
                fixed_numbers.append(number)

    if fixed_numbers:
        with fixed_numbers_file.open("a", encoding="utf-8") as fixed_output:
            for number in fixed_numbers:
                fixed_output.write(f"{number}\n")


def _is_fixed_line_number(number: str) -> bool:
    """Return ``True`` when ``number`` appears to represent a landline phone."""

    digits = re.sub(r"\D", "", number)
    if not digits:
        return False

    # Remove trunk prefix used in some formatted numbers (e.g., 0XXDDD...)
    if digits.startswith("0") and len(digits) > 10:
        digits = digits[1:]

    if len(digits) >= 10:
        subscriber = digits[-8:]
    elif len(digits) == 8:
        subscriber = digits
    else:
        return False

    if len(subscriber) != 8:
        return False

    return subscriber[0] in {"2", "3", "4", "5"}


if __name__ == "__main__":
    main()
