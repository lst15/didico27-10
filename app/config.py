"""Static configuration values used by the application."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .models import LoginRequest

DEFAULT_URL = "https://consignadorapido.com/acesso/login_usuario?token_log=078gereh5n9jwc0vrhvre1i"

DEFAULT_HEADERS: Mapping[str, str] = {
    "Host": "consignadorapido.com",
    "sec-ch-ua-platform": '"Linux"',
    "x-requested-with": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "sec-ch-ua": '"Brave";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "sec-ch-ua-mobile": "?0",
    "sec-gpc": "1",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Origin": "https://consignadorapido.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://consignadorapido.com/",
    "Priority": "u=1, i",
    # If you prefer, remove Cookie here and use session.cookies.set(...) below
    "Cookie": "PHPSESSID=k245sqdgimv74mqncu4pk12mf5",
}

DEFAULT_CREDENTIALS: Mapping[str, str] = {
    "login": "23027MJCONSULTORIA",
    "senha": "Carol@2024",
}

DEFAULT_CREDENTIALS_FILE = Path(__file__).resolve().parent.parent / "credentials.txt"

DEFAULT_LOGIN_REQUEST = LoginRequest(
    url=DEFAULT_URL,
    headers=DEFAULT_HEADERS,
    credentials=DEFAULT_CREDENTIALS,
)

__all__ = [
    "DEFAULT_URL",
    "DEFAULT_HEADERS",
    "DEFAULT_CREDENTIALS",
    "DEFAULT_CREDENTIALS_FILE",
    "DEFAULT_LOGIN_REQUEST",
]
