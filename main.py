import requests

url = "https://consignadorapido.com/acesso/login_usuario?token_log=078gereh5n9jwc0vrhvre1i"

headers = {
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

data = {
    "login": "23027MJCONSULTORIA",
    "senha": "Carol@2024"
}

# simple request
resp = requests.post(url, headers=headers, data=data, timeout=15)

print(resp.status_code)
try:
    print(resp.json())
except ValueError:
    print(resp.text)
