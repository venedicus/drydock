"""Командная строка. Всё то же, что в web UI, но пригодно для ночного
запуска через Планировщик: опись и пробы хочется гонять повторно, в том
числе когда никто не смотрит.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import archive as archive_mod
from . import cloud, config, db, download, probe, scan, tree
from .yandex import Disk


def human(n: float | None) -> str:
    size = float(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{int(size)} Б"
        size /= 1024
    return f"{size:.1f} ТБ"


def _conn():
    config.PATHS.ensure()
    return db.connect(config.PATHS.db)


async def cmd_scan(args) -> int:
    conn = _conn()
    saved = db.kv_get(conn, scan.CHECKPOINT_KEY)
    if args.restart:
        db.kv_del(conn, scan.CHECKPOINT_KEY)
        saved = None
    elif saved and saved.get("root") == args.root:
        print(f"Опись продолжается с чекпоинта: в очереди "
              f"{len(saved.get('stack') or [])} папок (--restart -- начать заново)")
    async with Disk(config.require_token()) as disk:
        info = await disk.about()
        print(f"Облако: занято {human(info.get('used_space'))} "
              f"из {human(info.get('total_space'))}")
        result = await scan.scan(conn, disk, args.root, resume=not args.restart)
        print(f"Опись: файлов {result['files']}, папок {result['dirs']}, "
              f"объём {human(result['bytes'])}")
        if not args.no_previews:
            counters = await scan.harvest_previews(conn, disk)
            print(f"Превью: сохранено {counters['ok']}, нет у {counters['missing']}, "
                  f"ошибок {counters['error']} из {counters['total']}")
    path = scan.export_manifest(conn)
    print(f"Опись выгружена: {path}")
    return 0


async def cmd_previews(args) -> int:
    conn = _conn()
    async with Disk(config.require_token()) as disk:
        counters = await scan.harvest_previews(conn, disk, refresh=args.refresh)
    print(json.dumps(counters, ensure_ascii=False))
    return 0


async def cmd_probe(args) -> int:
    conn = _conn()
    paths = probe.select_paths(conn, under=args.under, states=args.states,
                               limit=args.limit, stale_hours=args.stale_hours,
                               skip_downloaded=not args.recheck_all)
    if not paths:
        print("Нечего проверять по заданным условиям.")
        return 0
    print(f"Проверяю {len(paths)} файлов (скачивания нет)...")
    async with Disk(config.require_token()) as disk:
        counters = await probe.run(conn, disk, paths)
    for state, n in sorted(counters.items(), key=lambda kv: -kv[1]):
        print(f"  {state:12} {n}")
    return 0


def cmd_status(_args) -> int:
    conn = _conn()
    t = tree.totals(conn)
    print(f"Опись:        файлов {t['files']}, папок {t['dirs']}, {human(t['bytes'])}")
    print(f"Доступно:     {t['ok']} ({human(t['ok_bytes'])})")
    print(f"Недоступно:   {t['unavailable']}   нет на сервере: {t['gone']}")
    print(f"Не проверено: {t['unchecked']}")
    print(f"Спасено:      {t['saved']} ({human(t['saved_bytes'])}), "
          f"с дырками {t['salvaged']}")
    print(f"Превью:       {t['previews']}")
    print(f"Архивы:       {t['archives']} наборов, {human(t['archive_bytes'])}")
    print(f"Убрано локально после архивации: {t['released']}")
    print(f"Удалено из облака: {t['cloud_deleted']}")
    return 0


async def cmd_download(args) -> int:
    conn = _conn()
    states = ["ok"] if not args.include_unchecked else ["ok", "unchecked"]
    paths = tree.subtree_files(conn, args.under, states=states, exclude_saved=True)
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        print("Нечего качать: под этой папкой нет доступных неспасённых файлов.")
        return 0
    info = download.plan(conn, paths)
    print(f"К выгрузке {info['count']} файлов, {human(info['bytes'])}")
    if args.dry_run:
        return 0
    async with Disk(config.require_token()) as disk:
        counters = await download.run(conn, disk, paths, salvage=args.salvage)
    for state, n in sorted(counters.items(), key=lambda kv: -kv[1]):
        print(f"  {state:16} {n}")
    return 0


def cmd_archive(args) -> int:
    conn = _conn()
    pend = archive_mod.pending(conn, None)
    print(f"Готово к упаковке: {len(pend)} файлов, "
          f"{human(sum(p['bytes'] for p in pend))}")
    if args.dry_run or not pend:
        return 0
    result = archive_mod.build(conn, None)
    for a in result["archives"]:
        print(f"  {a['name']}: файлов {a['files']}, томов {len(a['volumes'])}, "
              f"{human(a['bytes'])}")
        for v in a["volumes"]:
            print(f"      {v}")
    print("Оригиналы на месте. Унеси тома в Телеграм, затем release.")
    return 0


def cmd_archives(_args) -> int:
    conn = _conn()
    rows = conn.execute(
        """SELECT a.id, a.name, a.state, a.created_at,
                  (SELECT COUNT(*) FROM archive_members m WHERE m.archive_id=a.id) AS files,
                  (SELECT COALESCE(SUM(bytes),0) FROM archive_volumes v
                   WHERE v.archive_id=a.id) AS bytes
           FROM archives a ORDER BY a.created_at DESC""").fetchall()
    for r in rows:
        print(f"[{r['id']:3}] {r['name']}  {r['state']:9} "
              f"файлов {r['files']:5}  {human(r['bytes'])}")
    return 0


def cmd_release(args) -> int:
    conn = _conn()
    check = archive_mod.verify(conn, args.archive_id)
    print(f"Тома: целых {len(check['ok'])}, битых {len(check['bad'])}, "
          f"отсутствует {len(check['missing'])}")
    if check["bad"] or check["missing"]:
        print("Оригиналы не трогаю.")
        return 1
    if not args.yes:
        print("Добавь --yes, чтобы удалить локальные оригиналы этого архива.")
        return 0
    result = archive_mod.release(conn, args.archive_id)
    print(f"Убрано {result['released']} файлов, освобождено "
          f"{human(result['freed_bytes'])}")
    return 0


async def cmd_cloud_delete(args) -> int:
    conn = _conn()
    paths = tree.subtree_files(conn, args.under) if args.under else None
    allowed, blocked = cloud.eligible(conn, paths, level=args.level)
    reasons: dict[str, int] = {}
    for b in blocked:
        reasons[b["reason"]] = reasons.get(b["reason"], 0) + 1
    print(f"Подходит к удалению: {len(allowed)} файлов, "
          f"{human(sum(int(a['size'] or 0) for a in allowed))}")
    print(f"Отклонено: {len(blocked)}")
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:6}  {reason}")
    if args.confirm < 0:
        print("\nЭто НЕОБРАТИМО: permanently=true минует Корзину.")
        print(f"Если согласен -- повтори с --confirm {len(allowed)}")
        return 0
    async with Disk(config.require_token()) as disk:
        result = await cloud.delete(conn, disk, paths or [], level=args.level,
                                    confirm=args.confirm,
                                    permanently=not args.to_trash)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


async def cmd_adopt(args) -> int:
    """Забрать то, что уже лежит в папке клиента Яндекс.Диска."""
    from pathlib import Path as _P

    from . import adopt
    conn = _conn()
    source = _P(args.source) if args.source else adopt.DEFAULT_SOURCE
    info = adopt.survey(conn, source)
    if not info["exists"]:
        print(f"Папки {source} нет. Укажи её через --source.")
        return 1
    print(f"Папка: {info['source']}")
    print(f"Можно забрать: {info['files']} файлов, {human(info['bytes'])}")
    print(f"Из них не достать больше ниоткуда (нет в облаке): {info['only_here']}")
    print(f"Способ: {'копия' if args.copy else ('ссылка' if args.link else 'перенос')}")
    print("Заглушки без данных пропускаются: у них настоящий только размер.")
    if args.dry_run or not info["files"]:
        return 0
    mode = "copy" if args.copy else ("link" if args.link else "move")
    delete_cloud = not args.keep_cloud
    if delete_cloud:
        async with Disk(config.require_token()) as disk:
            counters = await adopt.run(conn, source, mode=mode,
                                       verify=not args.no_verify,
                                       delete_cloud=True, disk=disk)
    else:
        counters = await adopt.run(conn, source, mode=mode,
                                   verify=not args.no_verify,
                                   delete_cloud=False)
    for state, n in sorted(counters.items(), key=lambda kv: -kv[1] if isinstance(kv[1], int) else 0):
        if state != "bytes":
            print(f"  {state:12} {n}")
    print(f"  взято {human(counters.get('bytes', 0))}")
    return 0


def cmd_compact(_args) -> int:
    conn = _conn()
    r = scan.compact_catalog(conn)
    print(f"catalog.jsonl: {r['records']} записей, "
          f"{human(r['before'])} -> {human(r['after'])}")
    return 0


def cmd_export(_args) -> int:
    conn = _conn()
    print(f"Опись: {scan.export_manifest(conn)}")
    return 0


def cmd_app(args) -> int:
    from . import desktop
    # Аргумент главнее настроек: --port нужен для разового запуска.
    return desktop.run(args.port or config.port(),
                       keep_running=args.keep_running)


def cmd_serve(args) -> int:
    import uvicorn

    from . import server
    server.SERVE_PORT = args.port
    print(f"Drydock: http://127.0.0.1:{args.port}")
    uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


# ── доступ к Диску ───────────────────────────────────────────────────


def cmd_auth(args) -> int:
    """Данные приложения и токен. Секреты читаются из stdin, а не из
    аргументов: аргументы видны в истории команд и в списке процессов."""
    from . import oauth, secretstore

    if args.action == "status":
        st = secretstore.status()
        print(f"Хранилище:     {st['store']}")
        print(f"Шифрование:    {'DPAPI (учётная запись Windows)' if st['encrypted'] else 'НЕТ'}")
        print(f"Приложение:    {'задано, ClientID …' + st['client_id_tail'] if st['has_app'] else 'не задано'}")
        print(f"Токен:         {'есть' if st['has_token'] else 'нет'}")
        print(f"Refresh-токен: {'есть' if st['has_refresh'] else 'нет'}")
        if st.get("expires_at"):
            import datetime
            when = datetime.datetime.fromtimestamp(st["expires_at"])
            print(f"Действует до:  {when:%Y-%m-%d %H:%M}")
        if st.get("scope"):
            print(f"Права:         {st['scope']}")
        print(f"Redirect URI:  {oauth.redirect_uri(args.port)}")
        return 0

    if args.action == "app":
        client_id = args.client_id or input("ClientID: ").strip()
        if args.client_secret:
            client_secret = args.client_secret
        else:
            import getpass
            client_secret = getpass.getpass("Client secret (не отображается): ").strip()
        oauth.set_app(client_id, client_secret)
        print("Приложение записано в шифрованное хранилище.")
        print(f"Проверь, что в его настройках на oauth.yandex.ru указан Redirect URI:\n"
              f"  {oauth.redirect_uri(args.port)}")
        return 0

    if args.action == "login":
        if args.manual:
            info = oauth.start(args.port, manual=True)
            print(f"Открой ссылку, разреши доступ и вставь код:\n{info['url']}\n")
            code = input("Код: ").strip()
            oauth.exchange(code, manual=True, state=info["state"])
        else:
            oauth.local_flow(args.port)
        print("Токен получен и сохранён.")
        return 0

    if args.action == "refresh":
        oauth.refresh()
        print("Токен продлён.")
        return 0

    if args.action == "logout":
        oauth.logout(keep_app=not args.forget_app)
        print("Токен забыт." + ("" if args.forget_app else " Данные приложения остались."))
        return 0

    return 1


async def cmd_whoami(_args) -> int:
    conn_token = config.require_token()
    del conn_token
    async with Disk(config.require_token()) as disk:
        info = await disk.about()
    user = info.get("user") or {}
    print(f"Логин:  {user.get('login') or '—'}")
    print(f"Занято: {human(info.get('used_space'))} из {human(info.get('total_space'))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="drydock",
        description="Спасение коллекции с Яндекс.Диска")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="опись облака + превью")
    p.add_argument("--root", default="disk:/")
    p.add_argument("--no-previews", action="store_true")
    p.add_argument("--restart", action="store_true",
                   help="начать опись заново, игнорируя сохранённую очередь папок")
    p.set_defaults(fn=cmd_scan, is_async=True)

    p = sub.add_parser("previews", help="добрать превью")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(fn=cmd_previews, is_async=True)

    p = sub.add_parser("probe", help="проверить доступность без скачивания")
    p.add_argument("--under", default=None)
    p.add_argument("--states", nargs="*", default=None,
                   help="unchecked ok unavailable gone api_error unknown")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--stale-hours", type=float, default=None)
    p.add_argument("--recheck-all", action="store_true")
    p.set_defaults(fn=cmd_probe, is_async=True)

    p = sub.add_parser("status", help="что уже сделано")
    p.set_defaults(fn=cmd_status, is_async=False)

    p = sub.add_parser("download", help="выгрузить доступное")
    p.add_argument("--under", default="disk:/")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--salvage", action="store_true",
                   help="читать блоками, пропуская мёртвые участки")
    p.add_argument("--include-unchecked", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_download, is_async=True)

    p = sub.add_parser("archive", help="упаковать спасённое в 7z-тома")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_archive, is_async=False)

    p = sub.add_parser("archives", help="список архивов")
    p.set_defaults(fn=cmd_archives, is_async=False)

    p = sub.add_parser("release", help="убрать локальные оригиналы архива")
    p.add_argument("archive_id", type=int)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_release, is_async=False)

    p = sub.add_parser("cloud-delete", help="удалить спасённое из облака")
    p.add_argument("--under", default=None)
    p.add_argument("--level", choices=["downloaded", "archived"], default="downloaded",
                   help="downloaded -- хватает проверенной копии на диске; "
                        "archived -- вдобавок нужен проверенный архив")
    p.add_argument("--confirm", type=int, default=-1)
    p.add_argument("--to-trash", action="store_true",
                   help="в Корзину (она ещё 30 дней занимает место в квоте)")
    p.set_defaults(fn=cmd_cloud_delete, is_async=True)

    p = sub.add_parser("adopt", help="забрать файлы из папки клиента Яндекс.Диска")
    p.add_argument("--source", default=None, help="где лежит Яндекс.Диск")
    p.add_argument("--copy", action="store_true",
                   help="копировать, а не переносить")
    p.add_argument("--link", action="store_true",
                   help="жёсткая ссылка вместо переноса (файл остаётся в папке клиента)")
    p.add_argument("--keep-cloud", action="store_true",
                   help="не удалять облачную копию после сверки хеша")
    p.add_argument("--no-verify", action="store_true",
                   help="не сверять хеши (быстро, но файл будет unverified)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_adopt, is_async=True)

    p = sub.add_parser("compact", help="пересобрать catalog.jsonl без повторов")
    p.set_defaults(fn=cmd_compact, is_async=False)

    p = sub.add_parser("export", help="выгрузить опись в jsonl")
    p.set_defaults(fn=cmd_export, is_async=False)

    p = sub.add_parser("serve", help="локальный web UI")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve, is_async=False)

    p = sub.add_parser("app", help="запустить как настольное приложение")
    p.add_argument("--port", type=int, default=None,
                   help="порт окна (по умолчанию -- из настроек или 8765)")
    p.add_argument("--keep-running", action="store_true",
                   help="не останавливать сервер при закрытии окна")
    p.set_defaults(fn=cmd_app, is_async=False)

    p = sub.add_parser("auth", help="данные приложения и токен")
    p.add_argument("action",
                   choices=["status", "app", "login", "refresh", "logout"])
    p.add_argument("--port", type=int, default=8765,
                   help="порт redirect URI (должен совпадать с настройками приложения)")
    p.add_argument("--manual", action="store_true",
                   help="без localhost-адреса: код вставляется вручную")
    p.add_argument("--client-id", default=None)
    p.add_argument("--client-secret", default=None,
                   help="лучше не передавать здесь -- спросим скрытым вводом")
    p.add_argument("--forget-app", action="store_true",
                   help="при logout забыть и ClientID с secret")
    p.set_defaults(fn=cmd_auth, is_async=False)

    p = sub.add_parser("whoami", help="проверить доступ к Диску")
    p.set_defaults(fn=cmd_whoami, is_async=True)

    ap.add_argument("--log", default=None, metavar="УРОВЕНЬ",
                    help="DEBUG показывает каждый запрос и каждую пробу")

    args = ap.parse_args(argv)
    from . import logging_setup
    logging_setup.setup(args.log)
    if args.is_async:
        return asyncio.run(args.fn(args))
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
