"""HTTP client responsible for performing login requests."""

from __future__ import annotations

from typing import Mapping, MutableMapping

import requests

from .models import LoginRequest, LoginResponse, ServiceRequest


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

    def perform_authenticated(self, request: ServiceRequest) -> LoginResponse:
        """Execute a follow-up request using the authenticated session."""

        headers = _to_mutable(request.headers)
        cookie_header = _build_cookie_header(self._session, headers.get("Cookie"))
        if cookie_header is None:
            headers.pop("Cookie", None)
        else:
            headers["Cookie"] = cookie_header

        response = self._session.post(
            request.url,
            headers=headers,
            data=request.payload,
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


def _build_cookie_header(
    session: requests.Session, fallback: str | None
) -> str | None:
    """Generate a cookie header from the authenticated session."""

    cookies = session.cookies.get_dict()
    if cookies:
        return "; ".join(f"{name}={value}" for name, value in cookies.items())
    return fallback


__all__ = ["LoginClient"]
