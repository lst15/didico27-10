"""Entry point for executing the login request workflow."""

from __future__ import annotations

from app import DEFAULT_LOGIN_REQUEST, LoginClient


def main() -> None:
    """Execute the configured login request and print its outcome."""

    client = LoginClient()
    response = client.authenticate(DEFAULT_LOGIN_REQUEST)
    print(response.status_code)
    print(response.body)


if __name__ == "__main__":
    main()
