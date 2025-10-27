"""HTTP client responsible for performing login requests."""

from __future__ import annotations

from typing import Mapping, MutableMapping

import requests

from .models import LoginRequest, LoginResponse


class LoginClient:
    """Client responsible for sending authentication requests."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def authenticate(self, request: LoginRequest) -> LoginResponse:
        """Send the login request and normalize the response."""

        response = self._session.post(
            request.url,
            headers=_to_mutable(request.headers),
            data=_to_mutable(request.credentials),
            timeout=15,
        )
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return LoginResponse(status_code=response.status_code, body=body)


def _to_mutable(mapping: Mapping[str, str]) -> MutableMapping[str, str]:
    """Create a mutable copy of mapping objects for use with requests."""

    return dict(mapping)


__all__ = ["LoginClient"]
