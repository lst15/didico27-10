"""HTTP client responsible for performing login requests."""

from __future__ import annotations

from typing import Mapping, MutableMapping

import requests

from .config import PROFILE_HEADERS, PROFILE_URL_TEMPLATE
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
        return _normalize_response(response)

    def fetch_user_profile(self, uid: str) -> LoginResponse:
        """Retrieve the profile information for ``uid`` using the active session."""

        response = self._session.get(
            PROFILE_URL_TEMPLATE.format(uid=uid),
            headers=_to_mutable(PROFILE_HEADERS),
            timeout=15,
        )
        return _normalize_response(response)


def _to_mutable(mapping: Mapping[str, str]) -> MutableMapping[str, str]:
    """Create a mutable copy of mapping objects for use with requests."""

    return dict(mapping)


def _normalize_response(response: requests.Response) -> LoginResponse:
    """Parse the response body, returning a :class:`LoginResponse` instance."""

    try:
        body = response.json()
    except ValueError:
        body = response.text
    return LoginResponse(status_code=response.status_code, body=body)


__all__ = ["LoginClient"]
