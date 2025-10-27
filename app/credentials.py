"""Utilities for loading and iterating credential data."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Mapping, MutableMapping

from .models import LoginRequest

DEFAULT_DELIMITER = "|"


class CredentialFormatError(ValueError):
    """Raised when a credential line cannot be parsed."""


def load_credentials(
    source: str | Path,
    *,
    delimiter: str = DEFAULT_DELIMITER,
) -> list[MutableMapping[str, str]]:
    """Load credential pairs from the given text file.

    Blank lines and lines starting with ``#`` are ignored. Each non-empty
    line must contain two values separated by ``delimiter``. Whitespace around
    the login or password is stripped.
    """

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Credential file not found: {path}")

    credentials: list[MutableMapping[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            login, password = (part.strip() for part in line.split(delimiter, 1))
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise CredentialFormatError(
                f"Line {line_number} of {path} does not contain the delimiter '{delimiter}'."
            ) from exc
        if not login or not password:
            raise CredentialFormatError(
                f"Line {line_number} of {path} must contain both login and password values."
            )
        credentials.append({"login": login, "senha": password})

    if not credentials:
        raise CredentialFormatError(f"No credentials found in {path}.")

    return credentials


def iter_login_requests(
    base_request: LoginRequest,
    credential_sets: Iterable[Mapping[str, str]],
) -> Iterator[LoginRequest]:
    """Yield ``LoginRequest`` instances for each credential mapping provided."""

    for credentials in credential_sets:
        yield base_request.with_overrides(credentials=credentials)


__all__ = [
    "CredentialFormatError",
    "DEFAULT_DELIMITER",
    "iter_login_requests",
    "load_credentials",
]
