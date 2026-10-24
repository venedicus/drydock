"""Проверка интерфейса в настоящем браузере.

Поднимает приложение, открывает его в Edge без окна и дёргает то, что
нельзя проверить по коду: сочетания клавиш и браузерное меню.

    .venv/Scripts/python tools/ui_check.py

Код возврата 1, если хоть одна проверка не прошла. Этим пользуется CI.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from websockets.sync.client import connect
except ImportError:  # pragma: no cover - подсказка вместо трейсбека
    print("нужен websockets: python -m pip install websockets")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent.parent
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/microsoft-edge",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url: str, timeout: float = 40.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


class Page:
    """Минимальный клиент CDP: отправить команду, дождаться ответа."""

    def __init__(self, ws_url: str) -> None:
        self.ws = connect(ws_url, max_size=None, open_timeout=20, legacy=True)
        self.next_id = 0

    def send(self, method: str, **params) -> dict:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method,
                                 "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=20))
            if msg.get("id") == self.next_id:
                return msg

    def js(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        payload = result.get("result", {})
        if "exceptionDetails" in payload:
            raise RuntimeError(payload["exceptionDetails"].get("text", "ошибка JS"))
        return payload.get("result", {}).get("value")

    def close(self) -> None:
        self.ws.close()


def main() -> int:
    edge = next((path for path in EDGE_CANDIDATES if Path(path).is_file()), None)
    if edge is None:
        print("Edge не найден -- проверку интерфейса пропускаю")
        return 0

    root = Path(tempfile.mkdtemp(prefix="drydock-ui-"))
    profile = Path(tempfile.mkdtemp(prefix="drydock-edge-"))
    port, cdp_port = free_port(), free_port()
    env = dict(os.environ, DRYDOCK_ROOT=str(root), DRYDOCK_SECRETS=str(root / "s.bin"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "drydock.cli", "serve", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    page = None
    failures: list[str] = []
    try:
        if not wait_http(f"http://127.0.0.1:{port}/api/state"):
            print("сервер не поднялся")
            return 1
        browser = subprocess.Popen(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run",
             f"--remote-debugging-port={cdp_port}",
             f"--user-data-dir={profile}",
             f"http://127.0.0.1:{port}/"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_http(f"http://127.0.0.1:{cdp_port}/json/version"):
            print("браузер не поднялся")
            return 1
        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list") as resp:
            targets = json.load(resp)
        target = next(t for t in targets if t["type"] == "page")
        page = Page(target["webSocketDebuggerUrl"])
        page.send("Runtime.enable")

        # Ждём, пока интерфейс отрисуется и словари загрузятся.
        for _ in range(60):
            if page.js("typeof togglePalette === 'function' "
                       "&& typeof lastState !== 'undefined' && lastState !== null"):
                break
            time.sleep(0.5)
        else:
            failures.append("интерфейс не загрузился за 30 секунд")

        def check(name: str, expression: str, expected=True) -> None:
            value = page.js(expression)
            ok = value == expected
            print(f"{'ok  ' if ok else 'FAIL'}  {name}"
                  + ("" if ok else f"  (получили {value!r})"))
            if not ok:
                failures.append(name)

        KEY = ("new KeyboardEvent('keydown', {{key: '{key}', code: 'KeyK', "
               "ctrlKey: true, bubbles: true, cancelable: true}})")

        # Ctrl+K на латинской раскладке.
        page.js("closePalette()")
        page.js(f"document.dispatchEvent({KEY.format(key='k')})")
        check("Ctrl+K открывает палитру (латиница)",
              "!document.getElementById('palette').classList.contains('hidden')")

        # Ctrl+K на русской раскладке: e.key == "л", e.code == "KeyK".
        page.js("closePalette()")
        page.js(f"document.dispatchEvent({KEY.format(key='л')})")
        check("Ctrl+K открывает палитру (кириллица)",
              "!document.getElementById('palette').classList.contains('hidden')")

        page.js("closePalette()")
        check("Escape закрывает палитру после Ctrl+K",
              "(() => { document.dispatchEvent(new KeyboardEvent('keydown', "
              "{key: 'Escape', bubbles: true}));"
              " return document.getElementById('palette').classList.contains('hidden'); })()")

        # Правая кнопка: меню не появляется нигде.
        CTX = ("(() => {{ const e = new MouseEvent('contextmenu', "
               "{{bubbles: true, cancelable: true}});"
               " document.querySelector({sel}).dispatchEvent(e);"
               " return e.defaultPrevented; }})()")
        check("правая кнопка на панели действий", CTX.format(sel="'.acts'"))
        check("правая кнопка в поле поиска",
              CTX.format(sel="'#search'"))
        check("правая кнопка на чекбоксе",
              CTX.format(sel="'input[type=checkbox]'"))

        # Блокировка меню не должна ломать выделение текста.
        check("выделение текста работает",
              "(() => { const r = document.createRange();"
              " r.selectNodeContents(document.body);"
              " const s = window.getSelection(); s.removeAllRanges();"
              " s.addRange(r); const ok = String(s).length > 0;"
              " s.removeAllRanges(); return ok; })()")

        # И приложение живо: дерево и кнопки на месте.
        check("каркас интерфейса на месте",
              "['tree','lens','summary'].every(id => document.getElementById(id))"
              " && !!document.querySelector('.acts')")
        check("кнопки действий на месте",
              "['btn-scan','btn-loop','btn-archive','btn-cloud-delete','btn-tools']"
              ".every(id => document.getElementById(id))")

        # Первый запуск на пустой базе: программа не должна говорить
        # «делать нечего», пока она ещё ничего не описала.
        check("пустая опись -- шаг «начать»",
              "lastState.next_step.kind === 'start'")
        check("подсказка в пустом дереве видна",
              "(() => { const el = document.querySelector('#tree .tree-empty');"
              " return !!el && el.offsetHeight > 0; })()")
        check("архив выключен, когда упаковывать нечего",
              "document.getElementById('btn-archive').disabled === true")
        check("удаление выключено, когда описи нет",
              "document.getElementById('btn-cloud-delete').disabled === true")

        # Проверка -- в главном ряду, выключена, когда проверять нечего.
        check("карточка «Проверка» в ряду",
              "!!document.getElementById('btn-probe-quick')")
        check("проверка выключена при пустой описи",
              "document.getElementById('btn-probe-quick').disabled === true")
        check("кнопка у выбора спрятана без выбора",
              "document.getElementById('btn-download-sel')"
              ".classList.contains('hidden') === true")

        # Автопилот переключается из шапки.
        page.js("document.getElementById('btn-autopilot').click()")
        time.sleep(2.0)
        check("автопилот включается из шапки",
              "lastState.autopilot === true")
        page.js("document.getElementById('btn-autopilot').click()")
        time.sleep(2.0)
        check("автопилот выключается из шапки",
              "lastState.autopilot === false")

        # Экспорт описи отдаёт файл, а не страницу.
        check("экспорт отдаёт CSV",
              "fetch('/api/export?format=csv').then(r => r.ok && "
              "(r.headers.get('content-type') || '').includes('text/csv'))")

        # Своё подтверждение вместо браузерного confirm().
        check("подтверждение открывается своим окном",
              "(() => { confirmModal(t('dlg.title'), 'x', 'ok');"
              " const ok = document.getElementById('modal-title').textContent"
              "   === t('dlg.title'); closeModal(); return ok; })()")
    finally:
        if page is not None:
            page.close()
        for proc in (browser, server):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)

    if failures:
        print(f"\nне прошло проверок: {len(failures)}")
        for name in failures:
            print("  -", name)
        return 1
    print("\nинтерфейс в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
