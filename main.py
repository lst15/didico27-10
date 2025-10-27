"""Entry point for executing the login request workflow."""

from __future__ import annotations

import json
from collections.abc import Mapping
from html.parser import HTMLParser
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

        nb_identifier = _extract_nb_identifier(response.body)
        if nb_identifier is None:
            continue

        benefit_request = _build_benefit_request(
            DEFAULT_OFFLINE_REQUEST, nb_identifier
        )
        benefit_response = client.perform_authenticated(benefit_request)
        print(f"Requisição por benefício realizada com NB: {nb_identifier}")
        print(benefit_response.status_code)
        hidden_inputs = _extract_hidden_input_values(benefit_response.body)
        print(json.dumps(hidden_inputs, ensure_ascii=False))


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


def _extract_hidden_input_values(
    response_body: Mapping[str, object] | str,
) -> dict[str, str]:
    """Collect hidden input fields from an HTML response body."""

    if not isinstance(response_body, str):
        return {}

    parser = _HiddenInputParser()
    parser.feed(response_body)
    parser.close()
    return parser.hidden_inputs


class _HiddenInputParser(HTMLParser):
    """Parse HTML and extract hidden input fields."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden_inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return

        normalized_attrs = {
            (name.lower() if name else name): value for name, value in attrs
        }

        input_type = normalized_attrs.get("type")
        if not isinstance(input_type, str) or input_type.lower() != "hidden":
            return

        name_attr = normalized_attrs.get("name")
        value_attr = normalized_attrs.get("value")
        if not isinstance(name_attr, str) or not isinstance(value_attr, str):
            return

        self.hidden_inputs[name_attr] = value_attr


if __name__ == "__main__":
    main()
