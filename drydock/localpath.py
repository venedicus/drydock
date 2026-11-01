"""Перенос облачного пути в локальный -- структура ОДИН В ОДИН.

Замены имени набора одинаковы на всех системах, и это осознанно: зеркало
должно переезжать между Windows, macOS и Linux без переименования файлов.
Запрещённые в Windows символы (`:`, `?`, `*` ...) заменяются на похожие из
Unicode и на macOS, хотя там они разрешены, -- иначе одна и та же книга
называлась бы по-разному на разных машинах, а база с локальными путями
перестала бы совпадать с диском.

Дальше начинаются различия, которые нельзя игнорировать:

1. Длина КОМПОНЕНТА. Windows считает 255 символов, POSIX -- 255 БАЙТ.
   Для кириллицы это вдвое меньше символов: имя из 200 русских букв на
   Linux уже не создаётся (ENAMETOOLONG), хотя в Windows проходит.
   Поэтому обрезка считается в единицах системы (см. `_size`).

2. Длина пути. Windows снимает лимит суммы префиксом `\\\\?\\`; на POSIX
   такого префикса нет и он не нужен -- там длина пути не ограничена.
   Поэтому `extended()` на macOS и Linux возвращает путь как есть.

3. Запрещённые имена устройств (CON, PRN, COM1) -- беда только Windows, но
   подчёркивание ставится везде: имя не должно зависеть от системы.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import hostos

# Замены для символов, запрещённых в именах файлов Windows. Диапазон U+F0xx --
# частная область Unicode, его же использует WSL для той же цели.
ILLEGAL = {
    '"': "\uf022",
    "*": "\uf02a",
    ":": "\uf03a",
    "<": "\uf03c",
    ">": "\uf03e",
    "?": "\uf03f",
    "\\": "\uf05c",
    "|": "\uf07c",
}
RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Лимит на ОДНУ часть пути. Windows считает символы, POSIX -- байты.
MAX_COMPONENT = 255
# Хвост-различитель: обрезка начала одного длинного имени может совпасть
# с обрезкой другого -- в зеркале две разные книги схлопнулись бы в один
# файл, и вторая затирала бы первую. Хеш от полного имени этого избегает.
HASH_CHARS = 8


def _size(text: str) -> int:
    """Сколько «весит» имя для файловой системы этой машины."""
    return len(text) if hostos.IS_WINDOWS else len(text.encode("utf-8"))


def _fits(text: str) -> bool:
    return _size(text) <= MAX_COMPONENT


def _cut_head(text: str, budget: int) -> str:
    """Наибольшее начало строки, влезающее в бюджет (в единицах системы)."""
    out: list[str] = []
    used = 0
    for ch in text:
        step = _size(ch)
        if used + step > budget:
            break
        out.append(ch)
        used += step
    return "".join(out)


def _cut_tail(text: str, budget: int) -> str:
    """Наибольший конец строки, влезающий в бюджет."""
    out: list[str] = []
    used = 0
    for ch in reversed(text):
        step = _size(ch)
        if used + step > budget:
            break
        out.append(ch)
        used += step
    return "".join(reversed(out))


def shorten(name: str) -> str:
    r"""Ужать одну часть пути до лимита, если она длиннее.

    Лимит компонента -- свойство ФАЙЛОВОЙ СИСТЕМЫ, и режимом открытия его не
    обойти: имя на 259 символов не существует на диске в принципе. В Windows
    это 255 символов (префикс \\?\ снимает только лимит СУММЫ пути, поэтому
    старый код падал с Errno 22 на длинном имени, уже имея префикс), на
    macOS и Linux -- 255 БАЙТ UTF-8, то есть для кириллицы вдвое меньше
    символов.

    Детерминированно: хеш берём от полного имени, поэтому один и тот же
    файл всегда получает одно и то же локальное имя -- иначе между
    запусками опись и зеркало разъехались бы. Режем с ДВУХ концов:
    начало несут книги с длинными названиями, а конец -- том, год,
    формат, часто единственное, чем две книги одного автора отличаются
    на глаз. Оригинал целиком остаётся в описи и манифесте архива.
    """
    if _fits(name):
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    else:
        ext = dot + ext
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:HASH_CHARS]
    # «…» и «_» -- разделители. «…» в UTF-8 занимает три байта, поэтому
    # бюджет считается той же мерой, что и лимит: иначе на POSIX имя
    # выходит ровно на два байта длиннее лимита (проверено тестом).
    marks = _size("…") + _size("_")
    budget = MAX_COMPONENT - _size(ext) - HASH_CHARS - marks
    if budget < 16:  # абсурдное расширение -- жертвуем им, имя важнее
        stem, ext, budget = name, "", MAX_COMPONENT - HASH_CHARS - marks
    head = _cut_head(stem, budget * 5 // 8)
    tail = _cut_tail(stem, budget - _size(head))
    return f"{head}…{tail}_{digest}{ext}"


def safe_component(name: str) -> str:
    """Одна часть пути, пригодная для Windows."""
    out = "".join(ILLEGAL.get(ch, ch) for ch in name)
    # Управляющие символы в именах встречаются у битых выгрузок.
    out = "".join(ch if ch >= " " else "_" for ch in out)
    # Точка и пробел в конце: Windows их молча срезает, и путь перестаёт
    # совпадать с тем, что мы записали в базе.
    out = out.rstrip(" .") or "_"
    stem = out.split(".", 1)[0].upper()
    if stem in RESERVED:
        out = "_" + out
    return shorten(out)


def cloud_to_relative(cloud_path: str) -> Path:
    """disk:/Library/Sorted/Наука/book.pdf -> Library/Sorted/Наука/book.pdf"""
    p = cloud_path
    for prefix in ("disk:/", "disk:"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    p = p.lstrip("/")
    parts = [safe_component(part) for part in p.split("/") if part]
    return Path(*parts) if parts else Path()


def local_for(cloud_path: str, base: Path) -> Path:
    return Path(base) / cloud_to_relative(cloud_path)


def extended(path: Path) -> str:
    r"""Путь для передачи в open(): с префиксом \\?\, если он длинный.

    Префикс понимает только Windows; на macOS и Linux путь отдаётся как
    есть -- там длина пути не ограничена, а `\\?\` стал бы обычным именем
    файла и сломал бы открытие.
    """
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        p = p.absolute()
    s = str(p)
    if not hostos.IS_WINDOWS:
        return s
    if len(s) < 240 or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def ensure_parent(path: Path) -> None:
    parent = Path(path).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Длинный путь: создаём по частям через расширенную форму.
        import os
        os.makedirs(extended(parent), exist_ok=True)
