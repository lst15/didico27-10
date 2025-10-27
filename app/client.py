"""HTTP client responsible for performing login requests."""

from __future__ import annotations

from typing import Mapping, MutableMapping

import requests

from .config import PROFILE_HEADER_UPDATES, PROFILE_URL_TEMPLATE
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

    def fetch_user_profile(self, uid: str, login_headers: Mapping[str, str]) -> LoginResponse:
        """Retrieve the profile information for ``uid`` using the active session."""

        response = self._session.get(
            PROFILE_URL_TEMPLATE.format(uid=uid),
            headers=_derive_profile_headers(login_headers),
            timeout=15,
        )
        return _normalize_response(response)


def _to_mutable(mapping: Mapping[str, str]) -> MutableMapping[str, str]:
    """Create a mutable copy of mapping objects for use with requests."""

    return dict(mapping)


def _derive_profile_headers(login_headers: Mapping[str, str]) -> MutableMapping[str, str]:
    """Create headers for the profile request derived from ``login_headers``."""

    derived = _to_mutable(login_headers)

    # Remove headers that only apply to the login POST.
    for key in (
        "Content-Type",
        "Origin",
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-Site",
        "x-requested-with",
    ):
        derived.pop(key, None)

    derived.update(PROFILE_HEADER_UPDATES)

    return derived


def _normalize_response(response: requests.Response) -> LoginResponse:
    """Parse the response body, returning a :class:`LoginResponse` instance."""

    try:
        body = response.json()
    except ValueError:
        body = response.text
    return LoginResponse(status_code=response.status_code, body=body)


__all__ = ["LoginClient"]
