"""Клиент Яндекс.Диска, рассчитанный на раненое облако.

Главное здесь -- проба доступности БЕЗ скачивания. Наивная проверка
("ручка download вернула ссылку -- значит файл есть") врёт: в октябре 2026
ссылка выдавалась корректно, а хранилище за ней отвечало 504 Gateway
Time-out примерно через десять минут. Поэтому проба идёт до конца цепочки:

    GET /v1/disk/resources/download   -> href (downloader.disk.yandex.ru)
    GET href, БЕЗ перехода по 302     -> location (*.storage.yandex.net/rdisk/...)
    GET location, Range: bytes=0-0    -> отдал байт? значит файл живой

Тело запроса читается ровно один раз и поток сразу закрывается: ни одного
лишнего байта трафика, сколько бы файл ни весил.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import httpx

from . import config

log = logging.getLogger("drydock.yandex")
from .localpath import ensure_parent, extended

# Эти строки Яндекс отдаёт в теле, когда данных файла больше нет ни на одной
# живой машине. Для нас это не "ошибка сети", а приговор файлу -- и его
# полезно видеть в отчёте дословно.
FATAL_MARKERS = (
    "no more reliable hosts",
    "no successful lookup result",
    "file IO failure",
)

# Обход описи идёт днями и не имеет права умирать от одного сетевого
# моргания: 16 октября один getaddrinfo failed убил часовой проход на
# 3050-м файле. Неудачная страница переспрашивается вечно, пауза растёт
# до минуты -- столько живёт провал провода или DNS. Пауза пишется в
# лог, иначе «замершая» полоска прогресса неотличима от зависшей программы.
WALK_RETRY_MIN = 2.0
WALK_RETRY_MAX = 60.0


def _content_range_total(value: str | None) -> int:
    """'bytes 0-0/1244840' -> 1244840. Заголовка нет -- размер неизвестен."""
    if not value or "/" not in value:
        return 0
    total = value.rsplit("/", 1)[-1].strip()
    return int(total) if total.isdigit() else 0


async def _wait_or_stop(seconds: float,
                        should_stop: Callable[[], bool] | None = None) -> bool:
    """Пауза кусками по секунде: за это время виден запрос на отмену.

    True -- отмена попросили, ждать больше не нужно.
    """
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while True:
        if should_stop is not None and should_stop():
            return True
        left = end - loop.time()
        if left <= 0:
            return False
        await asyncio.sleep(min(1.0, left))


@dataclass
class Probe:
    """Что мы узнали о файле, не скачав его."""

    path: str
    state: str  # ok | unavailable | gone | api_error | unknown
    http_status: int | None = None
    storage_host: str | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.state == "ok"


class Disk:
    def __init__(self, token: str, *, concurrency: int | None = None) -> None:
        self._token = token
        limit = concurrency or config.CONCURRENCY
        # Наружу лимит нужен выгрузке: она гоняет файлы порциями через
        # gather, и порция УЖЕ лимита сводит его на нет -- сколько ни ставь
        # потоков, работать будет ширина порции.
        self.limit = limit
        self._sem = asyncio.Semaphore(limit)
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=False,
            timeout=httpx.Timeout(config.API_TIMEOUT, connect=15.0),
            limits=httpx.Limits(max_connections=limit * 2,
                                max_keepalive_connections=limit),
            # Только ASCII: HTTP-заголовки кодируются latin-1, и кириллица
            # здесь роняет httpx ещё при создании клиента -- то есть всё.
            headers={"User-Agent": "Drydock/0.1 (personal archive)"},
        )

    # ── служебное ────────────────────────────────────────────────────

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self._token}"}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _api(self, method: str, url: str, *, params: dict | None = None,
                   retries: int = 5) -> httpx.Response:
        """Запрос к cloud-api с отступом при 429/5xx.

        Облако сейчас само нестабильно, и единичная 503 от API ничего не
        говорит о файле -- надо просто переспросить.
        """
        delay = 1.0
        last: httpx.Response | None = None
        for attempt in range(retries):
            async with self._sem:
                try:
                    resp = await self._client.request(method, url, params=params,
                                                      headers=self._auth)
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == retries - 1:
                        raise
                    resp = None  # type: ignore[assignment]
            if resp is not None:
                if resp.status_code not in (429, 500, 502, 503, 504):
                    return resp
                last = resp
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                log.warning("API %s %s -> HTTP %s, попытка %s/%s, пауза %.1fс",
                            method, url.rsplit("/", 1)[-1], resp.status_code,
                            attempt + 1, retries, delay)
            await asyncio.sleep(delay + random.uniform(0, 0.4))
            delay = min(delay * 2, 30.0)
        assert last is not None
        return last

    # ── опись ────────────────────────────────────────────────────────

    async def about(self) -> dict:
        resp = await self._api("GET", config.API)
        resp.raise_for_status()
        return resp.json()

    async def listdir(self, path: str, *, offset: int = 0, limit: int = 500) -> dict:
        """Одна страница содержимого папки.

        Поля НЕ урезаем (нет параметра fields): нам нужно всё, что сервер
        ещё готов рассказать о файле -- это и есть спасаемая информация.
        """
        resp = await self._api("GET", f"{config.API}/resources", params={
            "path": path,
            "limit": limit,
            "offset": offset,
            "preview_size": config.PREVIEW_SIZE,
            "preview_crop": "false",
            "sort": "name",
        })
        if resp.status_code == 404:
            raise FileNotFoundError(path)
        resp.raise_for_status()
        return resp.json()

    async def walk(self, root: str | list[str] = "disk:/", *,
                   should_stop: Callable[[], bool] | None = None,
                   on_pending: Callable[[list[str]], None] | None = None
                   ) -> AsyncIterator[dict]:
        """Рекурсивный обход в глубину: отдаёт и файлы, и папки.

        Обходим дерево, а не плоский /resources/files, по двум причинам:
        плоский список не содержит папок (а структуру надо повторить один
        в один, включая пустые), и не даёт заметить, где обход сломался.

        Третья причина добавилась 16 октября: обход дней длины падал от
        одного сетевого моргания -- getaddrinfo failed на 3050-м файле
        убил часовую работу. Теперь неудачный запрос страницы не поднимает
        исключение, а ждёт и переспрашивает ту же страницу: смещение не
        сдвигается, дублей в описи не появится.

        root -- "disk:/" либо ГОТОВАЯ ОЧЕРЕДЬ папок. Очередь отдаёт опись,
        продолженная с чекпоинта: обход встаёт на оставшиеся папки, а не
        начинает облако с корня заново.

        should_stop -- проверка «не попросили ли отмену»: во время долгой
        паузы ретрая иначе не заметить нажатия «Стоп».
        on_pending -- колбэк с очередью папок. В очереди ВСЕГДА есть и
        папка, которая прямо сейчас перечисляется: прерванный обход
        продолжится с неё, а не потеряет её хвост. Перечисление пойдёт
        с нулевого смещения -- записи идемпотентны, лишние upsert'ы
        дешевле потерянных файлов.
        """
        stack = [root] if isinstance(root, str) else list(root)
        delay = WALK_RETRY_MIN
        while stack:
            folder = stack.pop()
            if on_pending is not None:
                on_pending(stack + [folder])
            offset = 0
            while True:
                try:
                    data = await self.listdir(folder, offset=offset)
                except FileNotFoundError:
                    break
                except Exception as exc:
                    # 401/403 ожиданием не лечатся: токен протух, нужен человек.
                    status = getattr(getattr(exc, "response", None),
                                     "status_code", None)
                    if status in (401, 403):
                        raise
                    log.warning("обход: %s не ответил (%s: %s), повтор через %.0fс",
                                folder, type(exc).__name__, str(exc)[:120], delay)
                    if await _wait_or_stop(delay, should_stop):
                        return
                    delay = min(delay * 2, WALK_RETRY_MAX)
                    continue
                delay = WALK_RETRY_MIN
                emb = data.get("_embedded") or {}
                items = emb.get("items") or []
                if offset == 0 and data.get("type") == "dir":
                    yield {k: v for k, v in data.items() if k != "_embedded"}
                for item in items:
                    yield item
                    if item.get("type") == "dir":
                        stack.append(item["path"])
                        if on_pending is not None:
                            on_pending(stack + [folder])
                offset += len(items)
                if len(items) == 0 or offset >= int(emb.get("total") or 0):
                    break
            if on_pending is not None:
                on_pending(list(stack))

    # ── проба доступности ────────────────────────────────────────────

    async def download_href(self, path: str, *,
                            retries: int = 5) -> tuple[str | None, int, str]:
        resp = await self._api("GET", f"{config.API}/resources/download",
                               params={"path": path}, retries=retries)
        if resp.status_code == 200:
            return resp.json().get("href"), 200, ""
        detail = resp.text[:300]
        return None, resp.status_code, detail

    async def probe(self, path: str) -> Probe:
        """Живы ли данные файла. Ни одного байта тела наружу."""
        result = await self._probe(path)
        # На DEBUG видно каждый файл с кодом и машиной хранилища -- именно
        # это нужно, когда разбираешься, почему конкретная книга не идёт.
        log.debug("проба %s -> %s (HTTP %s, %s) %s", path, result.state,
                  result.http_status, result.storage_host or "-",
                  (result.detail or "")[:120])
        if result.state in ("api_error", "unknown"):
            log.warning("проба %s: %s HTTP %s %s", path, result.state,
                        result.http_status, (result.detail or "")[:200])
        return result

    async def _probe(self, path: str) -> Probe:
        try:
            # Две попытки вместо пяти. Пятикратный ретрай с удвоением паузы
            # -- это до 31 секунды сна на ОДИН файл, а проба всё равно не
            # приговор: результат живёт ограниченное время и файл будет
            # опрошен снова. Лучше быстрый честный "api_error" сейчас, чем
            # полминуты ожидания ради той же записи.
            href, status, detail = await self.download_href(path, retries=3)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return Probe(path, "api_error", None, None, f"{type(exc).__name__}: {exc}")
        if href is None:
            state = "gone" if status == 404 else "api_error"
            return Probe(path, state, status, None, detail)

        url = href
        host: str | None = None
        # Переходы делаем руками: нам важно знать, на какой машине хранилища
        # лежит файл, и остановиться, если она не отвечает.
        for _ in range(5):
            try:
                got = await self._probe_once(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # Повисло на хранилище -- для нас это недоступность.
                return Probe(path, "unavailable", None, host,
                             f"{type(exc).__name__}: {exc}")
            status, location, body = got
            if location:
                url = str(httpx.URL(url).join(location))
                host = httpx.URL(url).host
                continue
            if status in (200, 206):
                return Probe(path, "ok", status, host)
            if status == 404:
                return Probe(path, "gone", status, host, body)
            if status in (500, 502, 503, 504) or any(m in body for m in FATAL_MARKERS):
                return Probe(path, "unavailable", status, host, body)
            return Probe(path, "unknown", status, host, body)
        return Probe(path, "unknown", None, host, "слишком много перенаправлений")

    async def _probe_once(self, url: str) -> tuple[int, str | None, str]:
        """Первый байт файла, а для больших -- ещё и последний.

        Первого байта мало: 18 октября «Конспект лекций по ТАУ.pdf»
        проходил пробу (HTTP 206, байт отдался), а выгрузка умирала на
        51910 из 1244840 -- хвост файла мёртв на машине хранилища. Такой
        файл нельзя ни скачать, ни спасти, а проба честно писала
        «доступно». Второй байт (последний в файле) стоит один запрос и
        ловит весь этот класс.
        """
        total = 0
        status = 0
        async with self._sem, self._client.stream(
            "GET", url, headers={"Range": "bytes=0-0"},
            timeout=httpx.Timeout(config.PROBE_TIMEOUT, connect=15.0),
        ) as resp:
            status = resp.status_code
            if resp.is_redirect:
                return resp.status_code, resp.headers.get("location"), ""
            if resp.status_code in (200, 206):
                async for _chunk in resp.aiter_bytes(1):
                    break  # байт получен -- файл отдаётся, больше не нужно
                total = _content_range_total(resp.headers.get("content-range"))
            else:
                body = (await resp.aread()).decode("utf-8", "replace")[:300]
                return resp.status_code, None, body
        if total > config.PROBE_TAIL_MIN and config.PROBE_TAIL \
                and not await self._byte_ok(url, total - 1):
            return 500, None, ("начало отдаётся, конец нет -- файл обрезан "
                               f"на машине хранилища ({total} байт в метаданных)")
        return status, None, ""

    async def _byte_ok(self, url: str, offset: int) -> bool:
        """Отдаётся ли байт по смещению. Тело не читаем, только первый байт.

        Две попытки: одиночный сетевой сбой не должен превращать живой
        файл в «обрезанный» -- проба пишет наблюдение, а не приговор.
        """
        for _ in range(2):
            try:
                async with self._sem, self._client.stream(
                    "GET", url,
                    headers={"Range": f"bytes={offset}-{offset}"},
                    timeout=httpx.Timeout(config.PROBE_TIMEOUT, connect=15.0),
                ) as resp:
                    if resp.status_code not in (200, 206):
                        return False
                    async for _chunk in resp.aiter_bytes(1):
                        return True
                    return False
            except (httpx.TimeoutException, httpx.TransportError):
                continue
        return False

    # ── превью ───────────────────────────────────────────────────────

    async def fetch_preview(self, url: str, dest: Path) -> tuple[str, int | None]:
        """Скачать превью. Оно крошечное и часто живо, когда оригинала уже нет."""
        try:
            async with self._sem:
                resp = await self._client.get(url, headers=self._auth,
                                              follow_redirects=True,
                                              timeout=httpx.Timeout(30.0, connect=15.0))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return f"error: {type(exc).__name__}", None
        if resp.status_code != 200 or not resp.content:
            return ("missing" if resp.status_code in (404, 410) else "error"), resp.status_code
        ensure_parent(dest)
        with open(extended(dest), "wb") as fh:  # noqa: ASYNC230 - буферизованная запись на локальный диск
            fh.write(resp.content)
        return "ok", 200

    # ── удаление из облака ───────────────────────────────────────────

    async def delete(self, path: str, *, permanently: bool = True) -> tuple[bool, str]:
        """Удалить ресурс из облака.

        permanently=True минует Корзину: файлы в Корзине ещё 30 дней
        занимают место в квоте, а смысл удаления ровно в том, чтобы место
        освободить.
        """
        resp = await self._api("DELETE", f"{config.API}/resources", params={
            "path": path,
            "permanently": "true" if permanently else "false",
        })
        if resp.status_code in (202, 204):
            return True, resp.text[:200]
        return False, f"HTTP {resp.status_code}: {resp.text[:300]}"

    # ── скачивание ───────────────────────────────────────────────────

    def open_range(self, href: str, start: int, end: int):
        """Поток одного куска по готовой ссылке -- для salvage-режима.

        Метод публичный нарочно: раньше salvage лез в disk._client и
        disk._token напрямую, и любая правка внутренностей клиента ломала
        бы его молча.
        """
        return self._client.stream(
            "GET", href, follow_redirects=True,
            headers={"Range": f"bytes={start}-{end}"} | self._auth,
            timeout=httpx.Timeout(config.PROBE_TIMEOUT, connect=15.0),
        )

    async def open_stream(self, path: str, *, start: int = 0):
        """Поток байтов файла с указанной позиции (для докачки).

        Ссылку берём заново на каждый вызов: у выгрузки это повторы --
        и новая ссылка может указывать на другую машину хранилища, когда
        прежняя рвёт передачу на середине.
        """
        href, status, detail = await self.download_href(path)
        if href is None:
            raise OSError(f"нет ссылки на {path}: HTTP {status} {detail}")
        headers: dict[str, Any] = dict(self._auth)
        if start:
            headers["Range"] = f"bytes={start}-"
        return self._client.stream(
            "GET", href, headers=headers, follow_redirects=True,
            timeout=httpx.Timeout(config.DOWNLOAD_READ_TIMEOUT, connect=20.0),
        )
