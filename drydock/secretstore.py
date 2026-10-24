"""Хранилище секретов: ClientID, Client secret и токены.

Шифруем через DPAPI (CryptProtectData) -- штатный механизм Windows. Ключ
не лежит в программе и не выводится из пароля: его держит система и
привязывает к учётной записи пользователя. Файл, скопированный на другую
машину или открытый под другим пользователем, не расшифруется.

Почему не просто .env: Client secret и refresh-токен дают полный доступ к
Диску на год вперёд. В открытом файле рядом с кодом им не место -- такой
файл легко уехать в git, в бэкап или в чужие руки вместе с ноутбуком.

Хранилище лежит ВНЕ репозитория -- в %LOCALAPPDATA%\\Drydock, чтобы
его нельзя было закоммитить случайно.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

# Приписка к шифру: расшифровать можно только тем же значением. Защищает от
# подмены файла другим DPAPI-блобом этого же пользователя.
ENTROPY = b"Drydock/yandex-disk/v1"
# Соль, с которой шифровали ДО переименования проекта. Менять её нельзя:
# это не имя, а параметр шифрования -- со сменой старые ключи перестают
# расшифровываться (DPAPI отдаёт «данные не расшифровываются», код 13).
# При чтении пробуем обе, при записи используется только ENTROPY.
LEGACY_ENTROPY = b"CloudRecovery/yandex-disk/v1"

CRYPTPROTECT_UI_FORBIDDEN = 0x01


def store_path() -> Path:
    override = os.environ.get("DRYDOCK_SECRETS")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "Drydock" / "credentials.bin"
    # Прежнее имя проекта: не заставляем входить заново после переименования.
    legacy = Path(base) / "CloudRecovery" / "credentials.bin"
    if not path.exists() and legacy.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(legacy.read_bytes())
        except OSError:
            pass
    return path


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _take(blob: _Blob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def _available() -> bool:
    return sys.platform == "win32"


def protect(data: bytes) -> bytes:
    if not _available():
        raise RuntimeError("DPAPI есть только в Windows")
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(_blob(data)), "Drydock",
        ctypes.byref(_blob(ENTROPY)), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptProtectData: {ctypes.GetLastError()}")
    return _take(out)


def _unprotect_with(data: bytes, entropy: bytes) -> bytes:
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(_blob(data)), None,
        ctypes.byref(_blob(entropy)), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptUnprotectData: код {ctypes.GetLastError()}")
    return _take(out)


def unprotect(data: bytes) -> bytes:
    if not _available():
        raise RuntimeError("DPAPI есть только в Windows")
    last: OSError | None = None
    for entropy in (ENTROPY, LEGACY_ENTROPY):
        try:
            return _unprotect_with(data, entropy)
        except OSError as exc:
            last = exc
    raise OSError(
        "CryptUnprotectData: не расшифровывается "
        f"({last}). Файл от другого пользователя или с другой машины -- "
        "введи данные приложения заново.")


# ── доступ к значениям ───────────────────────────────────────────────


def load() -> dict[str, Any]:
    path = store_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(unprotect(path.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}


def save(data: dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(protect(json.dumps(data, ensure_ascii=False).encode("utf-8")))
    os.replace(tmp, path)
    # Файл и так зашифрован, но пусть и права будут только у владельца.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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
    path = store_path()
    if path.is_file():
        path.unlink()


def status() -> dict[str, Any]:
    """Что наружу можно показать: признаки, а не значения.

    Ни ClientID, ни secret, ни токен не возвращаются никогда -- UI и логи
    видят только "есть/нет" и хвост ClientID для опознания приложения.
    """
    data = load()
    cid = data.get("client_id") or ""
    return {
        "has_app": bool(cid and data.get("client_secret")),
        "client_id_tail": cid[-6:] if cid else "",
        "has_token": bool(data.get("access_token")),
        "has_refresh": bool(data.get("refresh_token")),
        "expires_at": data.get("expires_at"),
        "scope": data.get("scope"),
        "store": str(store_path()),
        "encrypted": _available(),
    }
