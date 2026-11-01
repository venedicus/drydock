"""Хранилище секретов: ClientID, Client secret и токены.

Чем шифруем -- зависит от системы, и это единственное место, где такая
разница есть:

* Windows -- DPAPI (CryptProtectData). Ключ держит система и привязывает к
  учётной записи: файл, скопированный на другую машину, не расшифруется.
* macOS -- связка ключей (Keychain) через штатную утилиту `security`.
  Тот же смысл: секрет доступен только этому пользователю на этой машине.
* Linux -- libsecret (`secret-tool`), если служба секретов запущена; иначе
  файл с правами 0600. Честно показываем это в интерфейсе: «шифрование:
  файл 0600» -- не то же самое, что DPAPI.

Почему не просто .env: Client secret и refresh-токен дают полный доступ к
Диску на год вперёд. В открытом файле рядом с кодом им не место -- такой
файл легко уехать в git, в бэкап или в чужие руки вместе с ноутбуком.

Хранилище лежит ВНЕ репозитория -- в каталоге приложения (см. hostos.app_dir),
чтобы его нельзя было закоммитить случайно.

Переменная DRYDOCK_SECRETS переводит хранилище в файл по указанному пути:
этим пользуются тесты и разовые запуски, чтобы не трогать настоящую связку
ключей. Шифрования в этом режиме нет -- он для изоляции, а не для работы.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import hostos

# Приписка к шифру: расшифровать можно только тем же значением. Защищает от
# подмены файла другим DPAPI-блобом этого же пользователя.
ENTROPY = b"Drydock/yandex-disk/v1"
# Соль, с которой шифровали ДО переименования проекта. Менять её нельзя:
# это не имя, а параметр шифрования -- со сменой старые ключи перестают
# расшифровываться (DPAPI отдаёт «данные не расшифровываются», код 13).
# При чтении пробуем обе, при записи используется только ENTROPY.
LEGACY_ENTROPY = b"CloudRecovery/yandex-disk/v1"

CRYPTPROTECT_UI_FORBIDDEN = 0x01

# Имена записи в связке ключей и в службе секретов.
SERVICE = "Drydock"
ACCOUNT = "credentials"


def _override() -> Path | None:
    raw = os.environ.get("DRYDOCK_SECRETS")
    return Path(raw) if raw else None


def store_path() -> Path:
    """Файл хранилища. На macOS и Linux его может не быть вовсе."""
    override = _override()
    if override:
        return override
    base = hostos.app_dir()
    name = "credentials.json" if backend() == "file" else "credentials.bin"
    path = base / name
    # Прежнее имя проекта: не заставляем входить заново после переименования.
    legacy = hostos.legacy_app_dir() / "credentials.bin"
    if not path.exists() and legacy.exists() and backend() == "dpapi":
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(legacy.read_bytes())
        except OSError:
            pass
    return path


def store_ref() -> str:
    """Строка «где лежит» для интерфейса. Не секрет и не путь-обманка."""
    kind = backend()
    if kind == "keychain":
        return f"keychain:{SERVICE}/{ACCOUNT}"
    if kind == "libsecret":
        return f"secret-service:{SERVICE}/{ACCOUNT}"
    return str(store_path())


def backend() -> str:
    """Кто отвечает за секрет: dpapi, keychain, libsecret или file."""
    if _override():
        return "file"
    if hostos.IS_WINDOWS:
        return "dpapi"
    if hostos.IS_MACOS and shutil.which("security"):
        return "keychain"
    if shutil.which("secret-tool"):
        return "libsecret"
    return "file"


def backend_label() -> str:
    """Человеческое описание хранилища -- для консоли и интерфейса."""
    return {
        "dpapi": "DPAPI (учётная запись Windows)",
        "keychain": "связка ключей macOS",
        "libsecret": "libsecret (secret-tool)",
        "file": "файл 0600 без шифрования",
    }.get(backend(), backend())


# ── Windows: DPAPI ───────────────────────────────────────────────────
#
# ctypes.wintypes на других системах не импортируется вовсе, поэтому
# обёртка грузится лениво: на macOS и Linux этих строк не касаются.

_DPAPI: SimpleNamespace | None = None


def _dpapi() -> SimpleNamespace:
    global _DPAPI
    if _DPAPI is not None:
        return _DPAPI
    if not hostos.IS_WINDOWS:
        raise RuntimeError("DPAPI есть только в Windows")

    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(data: bytes) -> Blob:
        buf = ctypes.create_string_buffer(data, len(data))
        return Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def take(part: Blob) -> bytes:
        out = ctypes.string_at(part.pbData, part.cbData)
        ctypes.windll.kernel32.LocalFree(part.pbData)
        return out

    def protect(data: bytes) -> bytes:
        out = Blob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob(data)), "Drydock",
            ctypes.byref(blob(ENTROPY)), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise OSError(f"CryptProtectData: {ctypes.GetLastError()}")
        return take(out)

    def unprotect(data: bytes) -> bytes:
        last: OSError | None = None
        for entropy in (ENTROPY, LEGACY_ENTROPY):
            out = Blob()
            ok = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob(data)), None,
                ctypes.byref(blob(entropy)), None, None,
                CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
            if ok:
                return take(out)
            last = OSError(f"CryptUnprotectData: код {ctypes.GetLastError()}")
        raise OSError(
            "CryptUnprotectData: не расшифровывается "
            f"({last}). Файл от другого пользователя или с другой машины -- "
            "введи данные приложения заново.")

    _DPAPI = SimpleNamespace(protect=protect, unprotect=unprotect)
    return _DPAPI


def protect(data: bytes) -> bytes:
    """Зашифровать секрет штатным механизмом системы (Windows)."""
    return _dpapi().protect(data)


def unprotect(data: bytes) -> bytes:
    """Расшифровать секрет (Windows)."""
    return _dpapi().unprotect(data)


# ── macOS: связка ключей ─────────────────────────────────────────────


def _run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    # Код возврата разбираем сами: у `security` и `secret-tool` «не найдено» --
    # обычный ответ, а не авария.
    return subprocess.run(cmd, check=False, capture_output=True, text=True,
                          input=input_text, timeout=30,
                          creationflags=hostos.no_window())


def _keychain_read() -> bytes | None:
    proc = _run(["security", "find-generic-password", "-s", SERVICE,
                 "-a", ACCOUNT, "-w"])
    if proc.returncode != 0:
        return None
    return base64.b64decode((proc.stdout or "").strip() or "")


def _keychain_write(payload: bytes) -> None:
    secret = base64.b64encode(payload).decode("ascii")
    proc = _run(["security", "add-generic-password", "-U", "-s", SERVICE,
                 "-a", ACCOUNT, "-w", secret])
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout or "security").strip()[:300])


def _keychain_delete() -> None:
    _run(["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT])


# ── Linux: libsecret ─────────────────────────────────────────────────


def _libsecret_read() -> bytes | None:
    proc = _run(["secret-tool", "lookup", "service", SERVICE, "account", ACCOUNT])
    if proc.returncode != 0:
        return None
    return base64.b64decode((proc.stdout or "").strip() or "")


def _libsecret_write(payload: bytes) -> None:
    secret = base64.b64encode(payload).decode("ascii")
    proc = _run(["secret-tool", "store", "--label", SERVICE,
                 "service", SERVICE, "account", ACCOUNT], input_text=secret)
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout or "secret-tool").strip()[:300])


def _libsecret_delete() -> None:
    _run(["secret-tool", "clear", "service", SERVICE, "account", ACCOUNT])


# ── чтение и запись ──────────────────────────────────────────────────


def _read_payload() -> bytes | None:
    kind = backend()
    if kind == "dpapi":
        path = store_path()
        return unprotect(path.read_bytes()) if path.is_file() else None
    if kind == "keychain":
        return _keychain_read()
    if kind == "libsecret":
        return _libsecret_read()
    path = store_path()
    return path.read_bytes() if path.is_file() else None


def _write_payload(payload: bytes) -> None:
    kind = backend()
    if kind == "keychain":
        _keychain_write(payload)
        return
    if kind == "libsecret":
        _libsecret_write(payload)
        return
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(protect(payload) if kind == "dpapi" else payload)
    os.replace(tmp, path)
    # На Windows файл и так зашифрован; на остальных права -- единственная
    # защита, и они должны стоять до того, как в файле окажется секрет.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load() -> dict[str, Any]:
    try:
        payload = _read_payload()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return {}
    if not payload:
        return {}
    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError:
        return {}


def save(data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    _write_payload(payload)


def update(**fields: Any) -> dict[str, Any]:
    data = load()
    data.update({k: v for k, v in fields.items() if v is not None})
    save(data)
    return data


def forget(*keys: str) -> None:
    data = load()
    for k in keys:
        data.pop(k, None)
    save(data)


def clear() -> None:
    """Убрать секрет отовсюду, где он мог остаться."""
    kind = backend()
    if kind == "keychain":
        _keychain_delete()
    elif kind == "libsecret":
        _libsecret_delete()
    for path in (store_path(), hostos.legacy_app_dir() / "credentials.bin"):
        try:
            path.unlink()
        except OSError:
            pass


def status() -> dict[str, Any]:
    """Что наружу можно показать: признаки, а не значения.

    Ни ClientID, ни secret, ни токен не возвращаются никогда -- UI и логи
    видят только "есть/нет", хвост ClientID и название хранилища.
    """
    data = load()
    kind = backend()
    cid = data.get("client_id") or ""
    return {
        "has_app": bool(cid and data.get("client_secret")),
        "client_id_tail": cid[-6:] if cid else "",
        "has_token": bool(data.get("access_token")),
        "has_refresh": bool(data.get("refresh_token")),
        "expires_at": data.get("expires_at"),
        "scope": data.get("scope"),
        "store": store_ref(),
        "encrypted": kind != "file",
        "backend": kind,
    }
