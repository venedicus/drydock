"""Сверить ключи переводов: что используется в коде и что лежит в словарях.

Проверяет три вещи:

1. каждый ключ из `t("...")` и `data-i18n*` есть во всех шести языках;
2. коды, которые сервер отдаёт интерфейсу (`err.*` в HTTPException и
   `job_msg("...")` в задачах), тоже есть в словарях -- иначе человек
   увидит сырой ключ вместо объяснения;
3. в словарях нет ключей, на которые никто не ссылается.

    .venv/Scripts/python tools/check_keys.py

Код возврата 1, если что-то разошлось: этим пользуется CI.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
I18N = WEB / "i18n"
LANGS = ["ru", "en", "tr", "kk", "uz", "az"]
PLURAL = re.compile(r"\.(one|few|many|other)$")

# Семейства, которые собираются в коде по частям: их проверяем по списку
# значений из сервера, а не по литералам.
DYNAMIC = ("job.", "job.state.", "jobmsg.", "err.", "theme.", "reason.",
           "n.", "next.", "unit.", "auth.crypto.")


def strip_comments(text: str) -> str:
    """Убрать комментарии: ключ, упомянутый только в них, не используется."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


def sources() -> str:
    return "\n".join(
        strip_comments((WEB / name).read_text(encoding="utf-8"))
        for name in ("app.js", "i18n.js", "index.html"))


def load() -> dict[str, set[str]]:
    out = {}
    for lang in LANGS:
        data = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
        out[lang] = {PLURAL.sub("", key) for key in data}
    return out


def used_literal_keys(blob: str) -> set[str]:
    """Ключи из вызовов t(...) -- включая тернарники и шаблоны."""
    keys = set(re.findall(r"""\bt\(\s*["']([a-zA-Z0-9_.]+)["']""", blob))
    # t(условие ? "a" : "b")
    for left, right in re.findall(
            r"""t\([^)]*?\?\s*["']([a-zA-Z0-9_.]+)["']\s*:\s*["']([a-zA-Z0-9_.]+)["']""",
            blob):
        keys |= {left, right}
    keys |= set(re.findall(r'data-i18n(?:-title|-ph|-html)?="([a-zA-Z0-9_.]+)"',
                           blob))
    # Префиксы вида t("job." + kind) -- не ключи, а семейства.
    return {k for k in keys if not k.endswith(".")}


def server_codes() -> set[str]:
    """Коды из сервера: ошибки, сообщения задач, виды задач."""
    src = "\n".join(p.read_text(encoding="utf-8")
                    for p in (ROOT / "drydock").glob("*.py"))
    codes = {f"err.{m}" for m in re.findall(r'"code":\s*"err\.([a-zA-Z]+)"', src)}
    # База err.nothingToProbe разветвляется на Node/Cluster: интерфейс
    # подставляет нужную по наличию host/cluster.
    if "err.nothingToProbe" in codes:
        codes.discard("err.nothingToProbe")
        codes |= {"err.nothingToProbeNode", "err.nothingToProbeCluster"}
    codes |= {f"jobmsg.{m}" for m in re.findall(r'job_msg\(\s*"([a-z.]+)"', src)}
    kinds = set(re.findall(r'_spawn\(\s*"([a-z\-]+)"', src))
    kinds |= set(re.findall(r'job_start\(\s*\w+\s*,\s*"([a-z\-]+)"', src))
    codes |= {f"job.{k}" for k in kinds}
    codes |= {f"job.state.{s}" for s in
              ("running", "done", "failed", "cancelled", "interrupted", "partial")}
    codes |= {f"theme.{s}" for s in ("auto", "light", "dark")}
    return codes


def main() -> int:
    dicts = load()
    blob = sources()
    used = used_literal_keys(blob) | server_codes()
    ru = dicts["ru"]

    problems: list[str] = []

    for lang in LANGS:
        missing = sorted(used - dicts[lang])
        if missing:
            problems.append(f"{lang}: нет {len(missing)} ключей -> "
                            + ", ".join(missing[:8]))

    # Мёртвый ключ: на него нет ссылки в коде ни в каком виде.
    dead = sorted(k for k in ru
                  if k not in used and not k.startswith(DYNAMIC)
                  and f'"{k}"' not in blob and f"'{k}'" not in blob)
    if dead:
        problems.append(f"мёртвых ключей: {len(dead)} -> " + ", ".join(dead[:8]))

    if problems:
        print("ключи разошлись:")
        for line in problems:
            print("  " + line)
        return 1

    print(f"ключи в порядке: {len(ru)} в словаре, "
          f"{len(used)} используется, мёртвых нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
