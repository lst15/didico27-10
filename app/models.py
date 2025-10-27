"""Data models used across the application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping


@dataclass(frozen=True)
class LoginRequest:
    """Container for the information required to perform a login request."""

    url: str
    headers: Mapping[str, str]
    credentials: Mapping[str, str]

    def with_overrides(
        self,
        *,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        credentials: Mapping[str, str] | None = None,
    ) -> "LoginRequest":
        """Return a new request with the provided overrides."""

        return LoginRequest(
            url=url or self.url,
            headers=headers or self.headers,
            credentials=credentials or self.credentials,
        )


@dataclass(frozen=True)
class LoginResponse:
    """Normalized response returned by the login service."""

    status_code: int
    body: Dict[str, object] | str

