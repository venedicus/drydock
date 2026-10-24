"""Перенос облачного пути в локальный -- структура ОДИН В ОДИН, но Windows
накладывает три ограничения, которые нельзя игнорировать на коллекции книг.

1. Запрещённые символы. В облаке имя файла может содержать : ? * " < > |
   -- в Windows не может. Такие символы заменяем на похожие из Unicode
   (двоеточие -> U+F03A и т.п., как это делает WSL), поэтому имя остаётся
   читаемым, а подмена записана в базе: оригинал всегда известен из описи.

2. Длина компонента. ОДНА часть пути не может быть длиннее 255 символов,
   и префикс \\\\?\\ этого не отменяет: open() на таком имени падает с
   Errno 22 (ERROR_INVALID_NAME). 17 октября на имени книги в 285 символов
   («...Указатель книг и статей... Том 3. 1892.pdf») умерла порция превью
   после часа успешной описи. Теперь такое имя режется детерминированно.

3. Длина пути. Путь вида
   files/Library/Sorted/История/<длинное имя автора> - <длинное название>.pdf
   легко переваливает за 260 символов, и тогда open() падает. Отдаём ядру
   путь с префиксом \\\\?\\, который снимает ЛИМИТ СУММЫ (но не компонента).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

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

# Лимит Windows на ОДНУ часть пути. Префикс \\?\ его не снимает.
MAX_COMPONENT = 255
# Хвост-различитель: обрезка начала одного длинного имени может совпасть
# с обрезкой другого -- в зеркале две разные книги схлопнулись бы в один
# файл, и вторая затирала бы первую. Хеш от полного имени этого избегает.
HASH_CHARS = 8


def shorten(name: str) -> str:
    r"""Ужать одну часть пути до 255 символов, если она длиннее.

    Лимит компонента -- свойство ФАЙЛОВОЙ СИСТЕМЫ (NTFS, ReFS, exFAT --
    везде 255), и никаким режимом открытия его не обойти: имя на 259
    символов не существует на диске в принципе. Префикс \\?\ снимает
    только лимит СУММЫ пути (260) -- именно поэтому старый код падал
    с Errno 22 на длинном имени, имея на нём префикс.

    Детерминированно: хеш берём от полного имени, поэтому один и тот же
    файл всегда получает одно и то же локальное имя -- иначе между
    запусками опись и зеркало разъехались бы. Режем с ДВУХ концов:
    начало несут книги с длинными названиями, а конец -- том, год,
    формат, часто единственное, чем две книги одного автора отличаются
    на глаз. Оринал целиком остаётся в описи и манифесте архива.
    """
    if len(name) <= MAX_COMPONENT:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    else:
        ext = dot + ext
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:HASH_CHARS]
    # «…» и «_» -- два символа-разделителя.
    budget = MAX_COMPONENT - len(ext) - HASH_CHARS - 2
    if budget < 16:  # абсурдное расширение -- жертвуем им, имя важнее
        stem, ext, budget = name, "", MAX_COMPONENT - HASH_CHARS - 2
    head = budget * 5 // 8
    tail = budget - head
    return f"{stem[:head]}…{stem[-tail:]}_{digest}{ext}"


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

    Префикс требует абсолютного пути без . и .., поэтому сначала resolve.
    """
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        p = p.absolute()
    s = str(p)
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
