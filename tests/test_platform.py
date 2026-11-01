"""Переносимость: то, что на Windows и на POSIX различается.

Самые дорогие ошибки здесь молчаливые: неверный каталог настроек означает
«пропали настройки», неверный лимит имени -- ENAMETOOLONG на середине
спасательной операции, неверное хранилище токена -- «войди заново» на
каждом запуске.

Windows-ветки проверяются на настоящей Windows, а POSIX-ветки -- здесь,
подменой флагов системы: так они проходят и на сборочной машине, где нет
ни macOS, ни Linux. Настоящие macOS и Linux проверяет CI (см. ci.yml).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-platform-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import archive, config, hostos, localpath, secretstore

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def as_windows(monkeypatch) -> None:
    monkeypatch.setattr(hostos, "IS_WINDOWS", True)
    monkeypatch.setattr(hostos, "IS_MACOS", False)
    monkeypatch.setattr(hostos, "IS_POSIX", False)


def as_macos(monkeypatch) -> None:
    monkeypatch.setattr(hostos, "IS_WINDOWS", False)
    monkeypatch.setattr(hostos, "IS_MACOS", True)
    monkeypatch.setattr(hostos, "IS_POSIX", True)


def as_linux(monkeypatch) -> None:
    monkeypatch.setattr(hostos, "IS_WINDOWS", False)
    monkeypatch.setattr(hostos, "IS_MACOS", False)
    monkeypatch.setattr(hostos, "IS_POSIX", True)


def test_app_dir_per_os(monkeypatch, tmp_path) -> None:
    """Каталог настроек -- тот, который в системе принято чистить."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    as_windows(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert hostos.app_dir() == tmp_path / "Local" / "Drydock"

    as_macos(monkeypatch)
    assert hostos.app_dir() == (tmp_path / "Library" / "Application Support"
                                / "Drydock")

    as_linux(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert hostos.app_dir() == tmp_path / "cfg" / "Drydock"

    # Без XDG_CONFIG_HOME -- обычный ~/.config, а не что-то в домашней папке.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert hostos.app_dir() == tmp_path / ".config" / "Drydock"
    assert hostos.legacy_app_dir().name == "CloudRecovery"


def test_shorten_counts_bytes_on_posix(monkeypatch) -> None:
    """На macOS и Linux лимит компонента -- 255 БАЙТ, а не символов."""
    as_linux(monkeypatch)
    name = "я" * 300 + ".pdf"
    out = localpath.safe_component(name)
    assert len(out.encode("utf-8")) <= 255, len(out.encode("utf-8"))
    assert out.endswith(".pdf"), out
    assert out == localpath.safe_component(name), "обрезка детерминированная"
    # Два разных длинных имени не схлопываются в одно.
    assert localpath.safe_component("я" * 300 + " Другая.pdf") != out


def test_shorten_counts_chars_on_windows(monkeypatch) -> None:
    """В Windows тот же текст влезает по символам -- режем иначе."""
    as_windows(monkeypatch)
    name = "я" * 300 + ".pdf"
    out = localpath.safe_component(name)
    assert len(out) <= 255, len(out)
    assert len(out) > 200, "по символам бюджет вдвое больше, чем по байтам"
    assert out.endswith(".pdf"), out


def test_extended_has_no_prefix_outside_windows(monkeypatch, tmp_path) -> None:
    """`\\\\?\\` -- только Windows: на POSIX это было бы имя файла."""
    as_linux(monkeypatch)
    deep = tmp_path / ("x" * 120) / ("y" * 120) / "book.pdf"
    assert localpath.extended(deep) == str(deep.resolve())
    as_windows(monkeypatch)
    assert localpath.extended(deep).startswith("\\\\?\\")


def test_secret_backend_choice(monkeypatch) -> None:
    """Чем шифруем: DPAPI, связка ключей, libsecret или файл 0600."""
    monkeypatch.delenv("DRYDOCK_SECRETS", raising=False)

    as_windows(monkeypatch)
    assert secretstore.backend() == "dpapi"

    as_macos(monkeypatch)
    monkeypatch.setattr(secretstore.shutil, "which",
                        lambda name: "/usr/bin/security" if name == "security" else None)
    assert secretstore.backend() == "keychain"

    as_linux(monkeypatch)
    monkeypatch.setattr(secretstore.shutil, "which",
                        lambda name: "/usr/bin/secret-tool" if name == "secret-tool" else None)
    assert secretstore.backend() == "libsecret"

    # Ни службы секретов, ни утилит -- честный файл с правами 0600.
    monkeypatch.setattr(secretstore.shutil, "which", lambda name: None)
    assert secretstore.backend() == "file"
    assert "0600" in secretstore.backend_label()

    # Переменная для тестов и разовых запусков всегда означает файл.
    monkeypatch.setenv("DRYDOCK_SECRETS", str(ROOT / "x.bin"))
    assert secretstore.backend() == "file"


def test_secret_file_roundtrip_is_plain_and_private(monkeypatch, tmp_path) -> None:
    """Файловый режим: читается, права 0600, статус не врёт про шифрование."""
    path = tmp_path / "secrets.json"
    monkeypatch.setenv("DRYDOCK_SECRETS", str(path))
    secretstore.save({"access_token": "t0ken", "client_id": "abc"})

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["access_token"] == "t0ken"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600

    st = secretstore.status()
    assert st["has_token"] is True
    assert st["backend"] == "file"
    assert st["encrypted"] is False
    assert st["store"] == str(path)

    secretstore.clear()
    assert not path.exists()


def test_keychain_uses_security_cli(monkeypatch) -> None:
    """Связка ключей: секрет кладём и читаем через `security`, в base64."""
    payload = json.dumps({"access_token": "x"}).encode("utf-8")
    calls: list[tuple[list[str], str | None]] = []

    class Result:
        returncode = 0
        stdout = base64.b64encode(payload).decode("ascii")
        stderr = ""

    def fake_run(cmd, *, input_text=None):
        calls.append((cmd, input_text))
        return Result()

    monkeypatch.setattr(secretstore, "_run", fake_run)
    monkeypatch.setattr(secretstore, "backend", lambda: "keychain")

    assert secretstore._read_payload() == payload
    assert calls[-1][0][:2] == ["security", "find-generic-password"]

    secretstore._write_payload(payload)
    cmd, _ = calls[-1]
    assert cmd[:2] == ["security", "add-generic-password"]
    assert "-U" in cmd and "-w" in cmd
    # В командной строке -- base64, а не сырой JSON с кавычками.
    assert base64.b64decode(cmd[-1]) == payload


def test_libsecret_reads_from_stdin(monkeypatch) -> None:
    """libsecret: секрет уходит в stdin, а не в аргументы процесса."""
    payload = b'{"access_token": "y"}'
    seen: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = base64.b64encode(payload).decode("ascii")
        stderr = ""

    def fake_run(cmd, *, input_text=None):
        seen["cmd"] = cmd
        seen["input"] = input_text
        return Result()

    monkeypatch.setattr(secretstore, "_run", fake_run)
    monkeypatch.setattr(secretstore, "backend", lambda: "libsecret")

    secretstore._write_payload(payload)
    assert seen["cmd"][:3] == ["secret-tool", "store", "--label"]
    assert base64.b64decode(str(seen["input"])) == payload
    assert secretstore._read_payload() == payload


def test_reveal_command_per_os(monkeypatch, tmp_path) -> None:
    """Проводник, Finder и xdg-open -- разные команды и разные ключи."""
    file = tmp_path / "book.pdf"
    file.write_text("x", encoding="utf-8")
    seen: list[list[str]] = []
    monkeypatch.setattr(hostos.subprocess, "Popen",
                        lambda args, **kw: seen.append(list(args)))

    as_windows(monkeypatch)
    monkeypatch.setattr(hostos, "file_manager", lambda: ["explorer"])
    hostos.reveal(file)
    hostos.reveal(tmp_path)
    assert seen[0] == ["explorer", "/select,", str(file)]
    assert seen[1] == ["explorer", str(tmp_path)]

    seen.clear()
    as_macos(monkeypatch)
    monkeypatch.setattr(hostos, "file_manager", lambda: ["open"])
    hostos.reveal(file)
    hostos.reveal(tmp_path)
    assert seen[0] == ["open", "-R", str(file)]
    assert seen[1] == ["open", str(tmp_path)]

    seen.clear()
    as_linux(monkeypatch)
    monkeypatch.setattr(hostos, "file_manager", lambda: ["/usr/bin/xdg-open"])
    hostos.reveal(file)
    # Выделять файл xdg-open не умеет -- открываем папку, где он лежит.
    assert seen[0] == ["xdg-open", str(file.parent)]


def test_linux_file_manager_prefers_xdg_open(monkeypatch) -> None:
    as_linux(monkeypatch)
    monkeypatch.setattr(hostos.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == "gio" else None)
    assert hostos.file_manager() == ["/usr/bin/gio"]
    monkeypatch.setattr(hostos.shutil, "which", lambda name: None)
    assert hostos.file_manager() is None


def test_seven_zip_finds_zz_on_posix(monkeypatch, tmp_path) -> None:
    """7-Zip 21+ ставится как `7zz`, и его тоже надо находить."""
    exe = tmp_path / "7zz"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(archive.shutil, "which",
                        lambda name: str(exe) if name == "7zz" else None)
    assert archive.seven_zip() == exe

    monkeypatch.setattr(archive.shutil, "which", lambda name: None)
    assert archive.seven_zip() is None or archive.seven_zip().is_file()


def test_browser_candidates_per_os(monkeypatch) -> None:
    """Окно приложения открывает Chromium, а не «какой-нибудь браузер»."""
    as_macos(monkeypatch)
    cands = hostos.browser_candidates()
    assert any("Google Chrome.app" in c for c in cands), cands
    assert any("Microsoft Edge.app" in c for c in cands), cands

    as_linux(monkeypatch)
    monkeypatch.setattr(hostos.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name == "chromium" else None)
    assert hostos.browser_candidates() == ["/usr/bin/chromium"]

    as_windows(monkeypatch)
    assert any(c.endswith("msedge.exe") for c in hostos.browser_candidates())


def test_no_window_flags_only_on_windows(monkeypatch) -> None:
    """CREATE_NO_WINDOW -- понятие Windows; на POSIX флаг обязан быть нулём."""
    as_linux(monkeypatch)
    assert hostos.no_window() == 0
    as_windows(monkeypatch)
    assert hostos.no_window() == getattr(
        __import__("subprocess"), "CREATE_NO_WINDOW", 0)
