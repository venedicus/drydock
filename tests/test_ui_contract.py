"""Контракт интерфейса: то, что легко сломать незаметно.

Браузерные проверки живут в tools/ui_check.py -- они точные, но требуют
Edge. Здесь то же самое, но по исходникам: дешево, без браузера, ловит
случайное удаление обработчика.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_ctrl_k_ignores_keyboard_layout() -> None:
    """Ctrl+K ловится по e.code, а не по e.key.

    На русской раскладке e.key равен "л", и сочетание не срабатывало:
    жаловались, что палитра не открывается.
    """
    assert 'e.code === "KeyK"' in APP, "Ctrl+K должен сравниваться по e.code"
    # Проверка по e.key остаётся запасной для старых браузеров без e.code.
    assert 'e.key.toLowerCase() === "k"' in APP


def test_context_menu_blocked_everywhere() -> None:
    """Браузерное меню гасится на всей странице, без исключений."""
    handler = re.search(r'document\.addEventListener\("contextmenu".*?\}\);',
                        APP, re.DOTALL)
    assert handler, "нет обработчика contextmenu"
    body = handler.group(0)
    assert "preventDefault" in body
    # Раньше поля ввода и выделенный текст были исключением -- и меню
    # всплывало на чекбоксах и в поиске.
    assert "closest(\"input" not in body, "у меню не должно быть исключений"
    assert "getSelection" not in body, "выделение текста не должно отменять блокировку"


def test_shell_ids_for_browser_checks() -> None:
    """Опорные элементы, по которым проверяет себя tools/ui_check.py."""
    for element_id in ("tree", "lens", "summary", "palette", "modal",
                       "btn-scan", "btn-loop", "btn-archive",
                       "btn-cloud-delete", "btn-tools"):
        assert f'id="{element_id}"' in HTML, f"нет #{element_id}"


def test_palette_has_escape_and_arrows() -> None:
    """Палитра управляется с клавиатуры -- это её смысл."""
    assert 'closePalette' in APP
    assert 'e.key === "ArrowDown"' in APP
    assert 'e.key === "Enter"' in APP


def test_full_inventory_switch_reaches_the_server() -> None:
    """Галочка «полная опись» есть в окне и уходит на сервер.

    Опись пропускает известно пустые папки -- и человек должен иметь
    возможность это отключить, не лезя в консоль.
    """
    assert 'id="scan-full"' in HTML, "нет переключателя полной описи"
    assert "full:" in APP, "переключатель не уходит на сервер"
    assert 'data-i18n="scan.full"' in HTML, "нет подписи переключателя"


def test_download_and_loop_are_mutually_exclusive_in_ui() -> None:
    """Пока идёт любой вид выгрузки, второй не должен запускаться."""
    assert 'busyKinds.has("download")' in APP
    assert 'busyKinds.has("download-loop")' in APP
    assert 'const downloadBusy =' in APP


def test_file_detail_escapes_server_metadata() -> None:
    """Строковые поля из облака не должны попасть в innerHTML как HTML."""
    assert 'esc(d.mime || "—")' in APP
    assert 'esc(d.modified || "—")' in APP
    assert 'esc(d.probe_state)' in APP
    assert 'esc(d.md5 || "—")' in APP
    assert 'esc(d.sha256 || "—")' in APP
