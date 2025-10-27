"""Entry point for executing the login request workflow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode

from app import DEFAULT_LOGIN_REQUEST, DEFAULT_OFFLINE_REQUEST, LoginClient, ServiceRequest


SEARCH_VALUES_FILE = Path(__file__).resolve().parent / "search_values.txt"


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

    payload = _replace_search_value(base_request.payload, search_value)
    return ServiceRequest(
        url=base_request.url,
        headers=base_request.headers,
        payload=payload,
    )


def _replace_search_value(
    payload: Mapping[str, str] | str, search_value: str
) -> Mapping[str, str] | str:
    """Return the payload with the "busca" field replaced by ``search_value``."""

    if isinstance(payload, str):
        pairs = parse_qsl(payload, keep_blank_values=True)
        updated_pairs = []
        replaced = False
        for key, value in pairs:
            if key == "busca":
                updated_pairs.append((key, search_value))
                replaced = True
            else:
                updated_pairs.append((key, value))
        if not replaced:
            updated_pairs.append(("busca", search_value))
        return urlencode(updated_pairs, doseq=True)

    if isinstance(payload, Mapping):
        updated_payload = dict(payload)
        updated_payload["busca"] = search_value
        return updated_payload

    raise TypeError(
        "Tipo de payload não suportado para substituição dinâmica do campo 'busca'."
    )


if __name__ == "__main__":
    main()
