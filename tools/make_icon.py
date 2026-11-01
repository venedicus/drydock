"""Иконка приложения -- без Pillow и прочих зависимостей.

PNG и ICO собираются руками: PNG -- это zlib-сжатые строки пикселей в
обёртке из чанков, ICO -- заголовок и список вложенных PNG. Тридцать строк
кода против лишней зависимости в проекте, который должен просто работать.

    .venv/Scripts/python tools/make_icon.py

Кладёт assets/drydock.ico (для ярлыка) и web/favicon.ico (его Edge
показывает в заголовке окна и на панели задач).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SS = 4  # сглаживание: рисуем крупно, потом усредняем

BG = (34, 38, 47)
CLOUD = (92, 157, 237)
ARROW = (217, 161, 59)


def _rounded(x: float, y: float, w: int, r: float) -> bool:
    if r <= x <= w - r or r <= y <= w - r:
        return 0 <= x <= w and 0 <= y <= w
    cx = r if x < r else w - r
    cy = r if y < r else w - r
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _circle(x: float, y: float, cx: float, cy: float, r: float) -> bool:
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def draw(size: int) -> bytes:
    """RGBA-буфер иконки: облако и стрелка вниз -- вытаскиваем из облака."""
    n = size * SS
    u = n / 256.0  # координаты задаём в сетке 256, масштабируем
    acc = bytearray(n * n * 4)

    for py in range(n):
        for px in range(n):
            x, y = px + 0.5, py + 0.5
            if not _rounded(x, y, n, 52 * u):
                continue
            r, g, b = BG
            # Облако: объединение трёх кругов и полосы под ними.
            in_cloud = (
                _circle(x, y, 96 * u, 104 * u, 36 * u)
                or _circle(x, y, 140 * u, 88 * u, 46 * u)
                or _circle(x, y, 176 * u, 112 * u, 32 * u)
                or (64 * u <= x <= 192 * u and 104 * u <= y <= 136 * u)
            )
            if in_cloud:
                r, g, b = CLOUD
            # Стрелка вниз: древко и треугольник.
            in_shaft = 116 * u <= x <= 140 * u and 140 * u <= y <= 186 * u
            in_head = (
                y >= 182 * u and y <= 218 * u
                and abs(x - 128 * u) <= (36 * u) * (1 - (y - 182 * u) / (36 * u))
            )
            if in_shaft or in_head:
                r, g, b = ARROW
            i = (py * n + px) * 4
            acc[i:i + 4] = bytes((r, g, b, 255))

    # Усреднение SSxSS -> один пиксель.
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            tr = tg = tb = ta = 0
            for dy in range(SS):
                for dx in range(SS):
                    i = (((y * SS + dy) * n) + (x * SS + dx)) * 4
                    tr += acc[i]; tg += acc[i + 1]; tb += acc[i + 2]; ta += acc[i + 3]
            k = SS * SS
            j = (y * size + x) * 4
            out[j:j + 4] = bytes((tr // k, tg // k, tb // k, ta // k))
    return bytes(out)


def png(size: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def ico(sizes: list[int]) -> bytes:
    images = [(s, png(s, draw(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blobs = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return header + entries + blobs


def main() -> int:
    blob = ico([16, 24, 32, 48, 64, 128, 256])
    for dest in (ROOT / "assets" / "drydock.ico", ROOT / "web" / "favicon.ico"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        print(f"{dest}  ({len(blob)} байт)")
    # PNG нужен там, где .ico не понимают: ярлык в меню Linux, иконка окна
    # на macOS. Рисовать его отдельно незачем -- он уже есть внутри ico.
    png_path = ROOT / "assets" / "drydock.png"
    png_path.write_bytes(png(256, draw(256)))
    print(f"{png_path}  ({png_path.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
