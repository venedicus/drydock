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


def test_round_timing_lives_on_main_screen() -> None:
    """Настройку круга не надо искать в «Инструментах → Настройки».

    Она лежит в карточке главного экрана: четыре пресета одним кликом,
    точечные поля и переключатель автопилота. Раньше её вообще не было
    видно, и человек справедливо спросил, где она.
    """
    for element_id in ("round-card", "round-presets", "round-line",
                       "round-state", "round-on", "round-apply", "round-fine"):
        assert f'id="{element_id}"' in HTML, f"нет #{element_id}"
    # Карточка внутри <main>, а не в модалке Tools (та объявлена раньше).
    main_at, main_end = HTML.index("<main>"), HTML.index("</main>")
    assert main_at < HTML.index('id="round-card"') < main_end, \
        "карточка кругов должна быть на главном экране"
    assert 'id="round-card"' in HTML[HTML.index('<aside class="pane side">'):main_end], \
        "карточка кругов должна лежать в правой колонке"
    for preset in ("now", "m5", "h1", "gradual"):
        assert f'data-preset="{preset}"' in HTML, f"нет пресета {preset}"
    assert "renderRounds(s)" in APP, "карточка не рисуется из состояния"
    assert '"/api/rounds/config"' in APP, "пресеты не уходят на сервер"
    print("тайминг кругов: виден на главном экране, четыре пресета")


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


def test_empty_dirs_cleanup_is_on_main_screen() -> None:
    """Уборка пустых папок -- рядом с деревом, а не в «Инструментах».

    Человек видит пустые папки именно в дереве, поэтому и кнопка должна
    быть в той же шапке, со счётчиком и без похода в настройки.
    """
    import json

    pane_start = HTML.index('<section class="pane tree-pane">')
    pane = HTML[pane_start:HTML.index("</section>", pane_start)]
    assert 'id="btn-empty-dirs"' in pane, "кнопка не в шапке дерева"
    assert 'wrap($("btn-empty-dirs")' in APP, "нет обработчика кнопки"
    assert '"/api/empty-dirs/preview"' in APP, "нет предпросмотра"
    assert '"/api/empty-dirs"' in APP, "нет запуска задачи"
    assert '"empty-dirs": "btn-empty-dirs"' in APP, "кнопка не связана с задачей"
    assert 'busyKinds.has("empty-dirs")' in APP, "повторный запуск не закрыт"
    assert 't("ed.buttonCount"' in APP, "счётчик на кнопке не рисуется"
    assert 'id="ed-permanent"' in APP, "нет выбора Корзина / навсегда"
    assert 't("ed.confirmPermanent"' in APP, "нет второго подтверждения"
    # По завершении задачи надо честно сказать, что часть деревьев
    # осталась в облаке: живая проверка нашла в них файлы.
    assert 'wasBusy.has("empty-dirs")' in APP, "нет итога по задаче"
    assert 't("ed.done")' in APP, "нет сообщения об итоге"

    keys = ("err.noEmptyDirs", "job.empty-dirs", "ed.button",
            "ed.buttonCount", "ed.button.title", "ed.title", "ed.body",
            "ed.check", "ed.slow", "ed.found", "ed.sample", "ed.permanent",
            "ed.trash", "ed.go", "ed.none", "ed.confirmPermanent",
            "ed.started", "ed.done")
    for lang in ("ru", "en", "tr", "kk", "uz", "az"):
        d = json.loads((ROOT / "web" / "i18n" / f"{lang}.json")
                       .read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in d]
        assert not missing, f"{lang}: нет ключей {missing}"


def test_empty_dirs_full_live_scan_is_in_the_dialog() -> None:
    """Список по описи не единственный: есть полный живой обход облака.

    Папки, опустевшие после описи, в базе ещё числятся с файлами -- без
    обхода их не найти. Обход идёт отдельной задачей, а не в обработчике
    превью, иначе окно встало бы на тысячи сетевых запросов.
    """
    import json

    assert '"/api/empty-dirs/scan"' in APP, "нет запуска полного обхода"
    assert '?source=live' in APP, "нет превью по живому обходу"
    assert 'source: useLive ? "live" : "inventory"' in APP, \
        "уборка не различает источник списка"
    assert 'id="ed-live"' in APP, "нет выбора источника в окне"
    assert 'wasBusy.has("empty-dirs-scan")' in APP, \
        "нет итога по задаче обхода"
    assert 'busyKinds.has("empty-dirs-scan")' in APP, \
        "повторный обход не закрыт"
    assert 't("ed.liveScan")' in APP and 't("ed.liveNeeded")' in APP

    keys = ("ed.liveScan", "ed.liveScanStarted", "ed.liveScanDone",
            "ed.liveScanFailed", "ed.liveScanBusy", "ed.liveUse", "ed.liveNeeded",
            "ed.liveStale", "ed.liveWhy", "job.empty-dirs-scan",
            "err.liveScanNeeded", "err.liveScanStale",
            "err.badEmptyDirsSource", "err.unknownPreset")
    for lang in ("ru", "en", "tr", "kk", "uz", "az"):
        d = json.loads((ROOT / "web" / "i18n" / f"{lang}.json")
                       .read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in d]
        assert not missing, f"{lang}: нет ключей {missing}"
