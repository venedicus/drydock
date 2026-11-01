"""Проверка переводов.

Ловит ровно те поломки, которые иначе замечаешь уже в интерфейсе, и
обычно не на своём языке: ключ есть в коде, а в словаре его нет (увидишь
сырой "btn.scan"); ключ есть в русском, но забыт в казахском; в одном
языке подстановка {size}, а в другом её потеряли при переводе.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:  # pytest есть не всегда: файл умеет запускаться и напрямую.
    import pytest
except ImportError:  # pragma: no cover - режим без pytest
    pytest = None

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
I18N = WEB / "i18n"
LANGS = ("ru", "en", "tr", "kk", "uz", "az")

PLURAL_SUFFIX = re.compile(r"\.(one|few|many|other)$")


if pytest is not None:

    @pytest.fixture()
    def dicts():
        """Словари переводов. Без web/i18n проверка пропускается."""
        if not I18N.is_dir():
            pytest.skip("нет web/i18n -- сначала tools/make_i18n.py")
        return load()


def load() -> dict[str, dict[str, str]]:
    return {lang: json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
            for lang in LANGS}


def stems(dictionary: dict[str, str]) -> set[str]:
    """Ключи без суффикса формы: у русского .few и .many есть, у
    английского нет, и это нормально -- сравнивать надо основы."""
    return {PLURAL_SUFFIX.sub("", k) for k in dictionary}


def test_same_keys(dicts) -> None:
    base = stems(dicts["ru"])
    for lang in LANGS:
        keys = stems(dicts[lang])
        missing, extra = base - keys, keys - base
        assert not missing, f"{lang}: нет ключей {sorted(missing)[:10]}"
        assert not extra, f"{lang}: лишние ключи {sorted(extra)[:10]}"
    print(f"ключи совпадают во всех языках: {len(base)} строк × {len(LANGS)}")


def test_no_empty(dicts) -> None:
    for lang in LANGS:
        empty = [k for k, v in dicts[lang].items() if not str(v).strip()]
        assert not empty, f"{lang}: пустые строки {empty[:10]}"
    print("пустых строк нет")


def test_placeholders(dicts) -> None:
    """Подстановки должны совпадать: потерянный {size} -- дырка в тексте."""
    pat = re.compile(r"\{(\w+)\}")
    for key, ru_value in dicts["ru"].items():
        want = set(pat.findall(ru_value))
        for lang in LANGS:
            # У плюральных ключей форма может называться иначе (.many против
            # .other) -- тогда сверяем с любой формой той же основы.
            value = dicts[lang].get(key)
            if value is None:
                stem = PLURAL_SUFFIX.sub("", key)
                cand = [v for k, v in dicts[lang].items()
                        if PLURAL_SUFFIX.sub("", k) == stem]
                if not cand:
                    raise AssertionError(f"{lang}: нет ни одной формы {stem}")
                value = cand[0]
            got = set(pat.findall(value))
            assert got == want, (
                f"{lang}/{key}: подстановки {sorted(got)} вместо {sorted(want)}")
    print("подстановки совпадают")


def test_russian_plurals(dicts) -> None:
    """У русского три формы, у остальных две -- проверяем, что если ключ
    сделан множественным, формы есть везде, где нужно."""
    for key in dicts["ru"]:
        m = PLURAL_SUFFIX.search(key)
        if not m:
            continue
        stem = key[: m.start()]
        for lang in LANGS:
            forms = {k[len(stem) + 1:] for k in dicts[lang] if k.startswith(stem + ".")}
            need = {"one", "few", "many"} if lang == "ru" else {"one", "other"}
            assert need <= forms, f"{lang}/{stem}: нет форм {sorted(need - forms)}"
    print("формы множественного числа на месте")


def test_keys_used_exist(dicts) -> None:
    """Каждый ключ из кода и разметки должен быть в словаре."""
    ru = dicts["ru"]
    used: set[str] = set()

    js = (WEB / "app.js").read_text(encoding="utf-8")
    # t("key") и t('key') -- шаблонные строки в ключах не используем.
    used |= set(re.findall(r"""\bt\(\s*["']([\w.\-]+)["']""", js))
    # Составные: t("job." + j.kind) и t("job.state." + j.state).
    dynamic_prefixes = set(re.findall(r"""\bt\(\s*["']([\w.]+\.)["']\s*\+""", js))

    html = (WEB / "index.html").read_text(encoding="utf-8")
    used |= set(re.findall(r'data-i18n(?:-title|-ph|-html)?="([\w.\-]+)"', html))

    # Ключ, оканчивающийся точкой, -- это начало склейки t("job." + kind):
    # он проверяется отдельно, как префикс, а не как готовая строка.
    used = {k for k in used if not k.endswith(".")}
    known = stems(ru) | set(ru)
    missing = sorted(k for k in used if k not in known)
    assert not missing, f"нет в словаре: {missing}"

    for prefix in dynamic_prefixes:
        assert any(k.startswith(prefix) for k in ru), \
            f"префикс {prefix!r} используется, но ключей с ним нет"
    print(f"все {len(used)} ключей из кода и разметки найдены "
          f"(+{len(dynamic_prefixes)} динамических префикса)")


def test_job_states_covered(dicts) -> None:
    """Состояния работ приходят с сервера -- каждое должно переводиться."""
    # partial -- «готово с ошибками» (часть провалилась): появилось
    # после задачи #46, отчитавшейся done при 140 провалах.
    for state in ("running", "done", "failed", "cancelled", "interrupted",
                  "partial"):
        assert f"job.state.{state}" in dicts["ru"], state
    for kind in ("scan", "previews", "probe", "download", "archive", "cloud-delete"):
        assert f"job.{kind}" in dicts["ru"], kind
    print("состояния и виды работ переведены")


def test_js_syntax() -> None:
    """Синтаксис скриптов интерфейса.

    Сломанный app.js не даёт деградации: не грузится НИЧЕГО -- ни чипы, ни
    дерево, ни подписи, и страница выглядит пустой. Один раз так и вышло
    после правки, где в строку попал настоящий перенос строки. node --check
    ловит это за миллисекунды, а глазами видно только по пустому окну.
    """
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("node не найден -- проверка синтаксиса пропущена")
        return
    for name in ("app.js", "i18n.js"):
        proc = subprocess.run([node, "--check", str(WEB / name)], check=False,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        assert proc.returncode == 0, f"{name}: {proc.stdout} {proc.stderr}"
    print("синтаксис app.js и i18n.js: ок")


def test_next_step_kinds_covered(dicts) -> None:
    """У каждого вида шага должен быть свой текст.

    Карточка «Что дальше» собирает ключ из вида шага: t(`next.${kind}.lead`).
    Проверка «есть хоть один ключ с префиксом next.» это пропускала, и в
    карточке вместо текста висел сырой `next.scan.lead` -- на самом видном
    месте экрана. Поэтому виды берём ПРЯМО ИЗ СЕРВЕРА и требуем набор на
    каждый.
    """
    server = (ROOT / "drydock" / "server.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'"kind":\s*"(\w+)"', server))
    assert kinds, "не нашёл ни одного вида шага в server.py"

    ru = dicts["ru"]
    # busy и done -- состояния без действия, кнопка им не нужна.
    without_button = {"busy", "done"}
    missing = []
    for kind in sorted(kinds):
        for suffix in ("lead", "why"):
            if f"next.{kind}.{suffix}" not in ru:
                missing.append(f"next.{kind}.{suffix}")
        if kind not in without_button and f"next.{kind}.btn" not in ru:
            missing.append(f"next.{kind}.btn")
    assert not missing, f"нет текста для шагов: {missing}"
    print(f"карточка «Что дальше»: все {len(kinds)} видов шага переведены")


def test_no_duration_promises(dicts) -> None:
    """Тексты не обещают, сколько времени займёт прогон.

    Темп зависит от хранилища и меняется в разы, поэтому любое число здесь
    быстро расходится с тем, что видит человек.
    """
    banned = ("займёт около", "идти часами", "takes about", "can take hours")
    bad: list[str] = []
    for lang, dictionary in dicts.items():
        for key, text in dictionary.items():
            low = text.lower()
            for phrase in banned:
                if phrase in low:
                    bad.append(f"{lang}:{key}")
            if "{hours}" in text and key.startswith(("next.", "arch.")):
                bad.append(f"{lang}:{key}")
    assert not bad, f"текст обещает длительность: {bad}"
    print("прогнозов длительности в текстах нет")


def main() -> int:
    if not I18N.is_dir():
        print("нет web/i18n -- сначала tools/make_i18n.py", file=sys.stderr)
        return 1
    dicts = load()
    test_same_keys(dicts)
    test_no_empty(dicts)
    test_placeholders(dicts)
    test_no_duration_promises(dicts)
    test_russian_plurals(dicts)
    test_keys_used_exist(dicts)
    test_job_states_covered(dicts)
    test_next_step_kinds_covered(dicts)
    test_js_syntax()
    print("\nпереводы: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
