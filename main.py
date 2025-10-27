"""Entry point for executing the login request workflow."""

from __future__ import annotations

from app import DEFAULT_LOGIN_REQUEST, DEFAULT_OFFLINE_REQUEST, LoginClient


def main() -> None:
    """Execute the configured login request and print its outcome."""

    client = LoginClient()
    login_response = client.authenticate(DEFAULT_LOGIN_REQUEST)
    print(login_response.status_code)
    print(login_response.body)

    offline_response = client.perform_authenticated(DEFAULT_OFFLINE_REQUEST)
    print(offline_response.status_code)
    print(offline_response.body)


if __name__ == "__main__":
    main()
