"""Entry point for executing the login request workflow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

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


def main(credentials_file: str | Path | None = None) -> None:
    """Execute the login workflow for all credentials in ``credentials_file``."""

    source = Path(credentials_file) if credentials_file else DEFAULT_CREDENTIALS_FILE
    client = LoginClient()

    try:
        credential_sets = load_credentials(source)
    except (FileNotFoundError, CredentialFormatError) as exc:
        raise SystemExit(str(exc)) from exc

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
        print(profile.body)


if __name__ == "__main__":
    main()
