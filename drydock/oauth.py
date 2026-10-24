"""Получение и обновление токена Яндекс.Диска.

Берём authorization code flow, а не implicit, ровно по одной причине: он
отдаёт refresh-токен. Операция растянута на дни и много порций, часть
запусков ночные -- просить человека переавторизоваться посреди выгрузки
нельзя, программа должна продлевать доступ сама.

Код подхватывается двумя способами:

  авто -- Яндекс возвращает браузер на http://localhost:<порт>/auth/callback,
          и программа забирает код сама. Этот адрес надо один раз прописать
          в настройках приложения на oauth.yandex.ru;
  вручную -- если возиться с redirect URI не хочется: Яндекс показывает код
          на странице, его достаточно вставить в поле.

Ни токен, ни secret не печатаются и не попадают в логи: наружу уходят
только признаки из secretstore.status().
"""

from __future__ import annotations

import secrets as pysecrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import httpx

from . import secretstore

AUTHORIZE = "https://oauth.yandex.ru/authorize"
TOKEN = "https://oauth.yandex.ru/token"
DEFAULT_PORT = 8765
CALLBACK_PATH = "/auth/callback"

# Запас до истечения: обновляем заранее, чтобы токен не умер посреди
# многочасовой выгрузки.
REFRESH_MARGIN = 7 * 24 * 3600


def redirect_uri(port: int = DEFAULT_PORT) -> str:
    return f"http://localhost:{port}{CALLBACK_PATH}"


def set_app(client_id: str, client_secret: str) -> dict:
    """Запомнить приложение. Значения уходят сразу в шифрованное хранилище."""
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("нужны и ClientID, и Client secret")
    secretstore.update(client_id=client_id, client_secret=client_secret)
    return secretstore.status()


def start(port: int = DEFAULT_PORT, *, manual: bool = False) -> dict:
    """Собрать ссылку на страницу согласия."""
    data = secretstore.load()
    if not data.get("client_id"):
        raise ValueError("сначала укажи ClientID и Client secret приложения")
    state = pysecrets.token_urlsafe(16)
    secretstore.update(oauth_state=state)
    params = {
        "response_type": "code",
        "client_id": data["client_id"],
        "state": state,
        "force_confirm": "yes",
    }
    if not manual:
        params["redirect_uri"] = redirect_uri(port)
    return {"url": f"{AUTHORIZE}?{urllib.parse.urlencode(params)}",
            "state": state,
            "redirect_uri": params.get("redirect_uri", ""),
            "manual": manual}


def exchange(code: str, *, port: int = DEFAULT_PORT, manual: bool = False,
             state: str | None = None) -> dict:
    """Обменять код на токены."""
    data = secretstore.load()
    if not data.get("client_id") or not data.get("client_secret"):
        raise ValueError("нет данных приложения")
    if state is not None and data.get("oauth_state") and state != data["oauth_state"]:
        raise ValueError("state не совпал: запрос пришёл не от нашей авторизации")
    form = {
        "grant_type": "authorization_code",
        "code": (code or "").strip(),
        "client_id": data["client_id"],
        "client_secret": data["client_secret"],
    }
    if not manual:
        form["redirect_uri"] = redirect_uri(port)
    with httpx.Client(timeout=30) as client:
        resp = client.post(TOKEN, data=form)
    if resp.status_code != 200:
        raise ValueError(f"Яндекс отказал: HTTP {resp.status_code} {resp.text[:300]}")
    return _store_tokens(resp.json())


def _store_tokens(payload: dict) -> dict:
    expires_in = int(payload.get("expires_in") or 0)
    secretstore.update(
        access_token=payload.get("access_token"),
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope"),
        expires_at=int(time.time()) + expires_in if expires_in else None,
    )
    secretstore.forget("oauth_state")
    return secretstore.status()


def refresh() -> dict:
    data = secretstore.load()
    if not data.get("refresh_token"):
        raise ValueError("нет refresh-токена -- нужна повторная авторизация")
    with httpx.Client(timeout=30) as client:
        resp = client.post(TOKEN, data={
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
        })
    if resp.status_code != 200:
        raise ValueError(f"обновление не удалось: HTTP {resp.status_code} "
                         f"{resp.text[:300]}")
    return _store_tokens(resp.json())


def access_token() -> str | None:
    """Рабочий токен, при необходимости продлённый.

    Если продление не удалось, отдаём что есть: вдруг токен ещё жив, а
    сорвалась только сеть. Разбираться будет вызывающий, получив 401.
    """
    data = secretstore.load()
    token = data.get("access_token")
    if not token:
        return None
    expires_at = data.get("expires_at")
    if expires_at and data.get("refresh_token") \
            and expires_at - time.time() < REFRESH_MARGIN:
        try:
            refresh()
            return secretstore.load().get("access_token")
        except (ValueError, httpx.HTTPError):
            return token
    return token


def logout(*, keep_app: bool = True) -> dict:
    """Забыть токены. Данные приложения по умолчанию остаются."""
    if keep_app:
        secretstore.forget("access_token", "refresh_token", "expires_at",
                           "scope", "oauth_state")
    else:
        secretstore.clear()
    return secretstore.status()


# ── флоу для командной строки ────────────────────────────────────────


class _Catcher(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        _Catcher.code = (q.get("code") or [None])[0]
        _Catcher.state = (q.get("state") or [None])[0]
        _Catcher.error = (q.get("error_description") or q.get("error") or [None])[0]
        body = ("Готово, можно закрыть вкладку и вернуться в Drydock."
                if _Catcher.code else f"Не получилось: {_Catcher.error}")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"<html><body style='font:16px sans-serif;padding:40px'>{body}"
            "</body></html>".encode())

    def log_message(self, *_args: object) -> None:
        pass  # не шумим в консоль


def local_flow(port: int = DEFAULT_PORT, *, timeout: float = 300) -> dict:
    """Открыть браузер и дождаться кода на локальный адрес."""
    info = start(port)
    _Catcher.code = _Catcher.state = _Catcher.error = None
    server = HTTPServer(("127.0.0.1", port), _Catcher)
    Thread(target=server.serve_forever, daemon=True).start()
    print(f"Открываю страницу согласия. Если браузер не открылся, зайди сам:\n"
          f"{info['url']}\n")
    webbrowser.open(info["url"])
    deadline = time.time() + timeout
    while time.time() < deadline and _Catcher.code is None and _Catcher.error is None:
        time.sleep(0.3)
    server.shutdown()
    if _Catcher.error:
        raise ValueError(f"Яндекс вернул ошибку: {_Catcher.error}")
    if _Catcher.code is None:
        raise ValueError("код не пришёл за отведённое время")
    return exchange(_Catcher.code, port=port, state=_Catcher.state)
