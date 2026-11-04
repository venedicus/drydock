"""Съёмка демо-гифок на синтетической базе.

    .venv/Scripts/python tools/make_demo.py            # все шесть языков
    .venv/Scripts/python tools/make_demo.py --langs ru  # один, для пробы

Поднимает сервер на временном корне с вымышленной коллекцией, открывает
интерфейс в headless Edge и снимает семь экранов рабочего цикла. Ни реальных
путей, ни имён файлов из коллекции, ни токенов в кадр не попадает.

Кадры складываются в GIF через ffmpeg (палитра считается один раз на весь
ролик). Зависимости: `websockets` (как у ui_check.py) и `ffmpeg` в PATH.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from ui_check import Page, free_port, wait_http

from drydock import db
from drydock.msg import job_msg

DEMO = Path(os.environ.get("DRYDOCK_DEMO_ROOT") or tempfile.gettempdir()) / "drydock-demo"
OUT = ROOT / "docs" / "images"
LANGS = ("ru", "en", "tr", "kk", "uz", "az")
WIDTH, HEIGHT = 1100, 660

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# Вымышленная коллекция: общие слова, латиница, никаких личных путей.
FOLDERS = (
    ("disk:/Library", "disk:/", "Library"),
    ("disk:/Library/Textbooks", "disk:/Library", "Textbooks"),
    ("disk:/Library/Fiction", "disk:/Library", "Fiction"),
    ("disk:/Documents", "disk:/", "Documents"),
    ("disk:/Documents/Reports", "disk:/Documents", "Reports"),
    ("disk:/Photos", "disk:/", "Photos"),
    ("disk:/Music", "disk:/", "Music"),
)
FILES: tuple[tuple[str, str, int, str], ...] = (
    ("disk:/Library/Textbooks/Algebra.pdf", "Algebra.pdf", 24, "ok"),
    ("disk:/Library/Textbooks/Geometry.pdf", "Geometry.pdf", 18, "ok"),
    ("disk:/Library/Textbooks/Physics.djvu", "Physics.djvu", 42, "unavailable"),
    ("disk:/Library/Textbooks/Chemistry.pdf", "Chemistry.pdf", 12, "ok"),
    ("disk:/Library/Fiction/Stories.fb2", "Stories.fb2", 3, "saved"),
    ("disk:/Library/Fiction/Novel.epub", "Novel.epub", 5, "saved"),
    ("disk:/Library/Fiction/Essays.pdf", "Essays.pdf", 9, "unavailable"),
    ("disk:/Documents/Reports/Summary-1.pdf", "Summary-1.pdf", 7, "ok"),
    ("disk:/Documents/Reports/Summary-2.pdf", "Summary-2.pdf", 8, "ok"),
    ("disk:/Documents/Reports/Draft.pdf", "Draft.pdf", 6, "unchecked"),
    ("disk:/Documents/Notes.txt", "Notes.txt", 1, "saved"),
    ("disk:/Documents/Scheme.png", "Scheme.png", 2, "unavailable"),
    ("disk:/Photos/Frame-001.jpg", "Frame-001.jpg", 4, "ok"),
    ("disk:/Photos/Frame-002.jpg", "Frame-002.jpg", 4, "ok"),
    ("disk:/Photos/Frame-003.jpg", "Frame-003.jpg", 5, "saved"),
    ("disk:/Photos/Panorama.jpg", "Panorama.jpg", 11, "unavailable"),
    ("disk:/Photos/Scan.tif", "Scan.tif", 28, "gone"),
    ("disk:/Music/Track-01.mp3", "Track-01.mp3", 8, "ok"),
    ("disk:/Music/Track-02.mp3", "Track-02.mp3", 9, "unchecked"),
    ("disk:/Music/Album.flac", "Album.flac", 61, "unavailable"),
    ("disk:/Archive-notes.txt", "Archive-notes.txt", 1, "saved"),
    ("disk:/Readme.md", "Readme.md", 1, "unchecked"),
)

INIT_JS = """
localStorage.setItem('cr-theme', 'dark');
localStorage.setItem('cr-scale', '100');
localStorage.setItem('cr-setup-hidden', '1');
"""

# Перед каждым кадром: убрать строку со свободным местом реального диска
# и любые абсолютные пути. Интерфейс перерисовывается сам, поэтому чистим
# прямо перед снимком.
CLEAN_JS = r"""
document.querySelectorAll('.tiles-foot').forEach(e => { e.style.display = 'none'; });
document.querySelectorAll('span,div,small,td').forEach(e => {
  if (!e.children.length && /[A-Z]:\\/.test(e.textContent)) e.style.display = 'none';
});
"""


def reset_db(path: Path) -> None:
    """Создать вымышленную опись, пробы и спасённые копии."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = db.connect(path)
    now = db.now()
    c.execute("PRAGMA journal_mode=WAL")
    for table in ("resources", "probe", "probe_history", "local", "jobs",
                  "archives", "archive_volumes", "archive_members",
                  "cloud_deleted", "kv", "meta_saved", "empty_dirs"):
        c.execute(f"DELETE FROM {table}")

    for folder, parent, name in FOLDERS:
        c.execute("""INSERT INTO resources(path,parent,name,type,size,raw,
                     first_seen,last_seen,modified) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (folder, parent, name, "dir", None,
                   json.dumps({"path": folder, "type": "dir", "name": name}),
                   now, now, "2026-10-20T10:00:00+00:00"))

    for i, (path_s, name, size_mb, state) in enumerate(FILES):
        parent = path_s.rsplit("/", 1)[0]
        size = size_mb * 1024 * 1024
        c.execute("""INSERT INTO resources(path,parent,name,type,size,md5,sha256,
                     mime,raw,first_seen,last_seen,modified)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (path_s, parent, name, "file", size,
                   f"demo-md5-{i:03d}", f"demo-sha256-{i:03d}",
                   "application/octet-stream",
                   json.dumps({"path": path_s, "type": "file", "name": name}),
                   now, now, "2026-10-20T10:00:00+00:00"))
        if state != "unchecked":
            http = {"ok": 206, "unavailable": 503, "gone": 404}.get(state, 200)
            c.execute("""INSERT INTO probe(path,state,http_status,storage_host,
                         checked_at,attempts) VALUES (?,?,?,?,?,1)""",
                      (path_s, state, http, "demo-node-1", now - 600))
        if state == "saved":
            local_file = DEMO / "files" / name
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"demo")
            c.execute("""INSERT INTO local(path,local_path,bytes,sha256,md5,
                         verify,downloaded_at,released,missing)
                         VALUES (?,?,?,?,?,'ok',?,0,0)""",
                      (path_s, str(local_file), size,
                       f"demo-sha256-{i:03d}", f"demo-md5-{i:03d}", now - 300))
        if i % 4 == 0:
            c.execute("""INSERT INTO meta_saved(path,preview_file,preview_state,
                         saved_at) VALUES (?,?, 'ok', ?)""",
                      (path_s, f"meta/previews/{name}.jpg", now - 200))

    c.execute("INSERT INTO kv(k,v) VALUES ('last_scan', ?)",
              (json.dumps(now - 3600),))
    c.execute("INSERT INTO kv(k,v) VALUES ('scan_queue', ?)",
              (json.dumps({"stack": []}),))
    # Одна завершённая задача, чтобы панель задач не была пустой.
    c.execute("""INSERT INTO jobs(id,kind,state,total,done,started_at,finished_at,
                 message) VALUES (1,'scan','ok',22,22,?,?,?)""",
              (now - 7200, now - 7100, job_msg("scan.count", files=22, dirs=7)))
    c.commit()
    c.close()


def set_jobs(path: Path, kind: str | None) -> None:
    """Показать нужную запущенную задачу (или убрать все)."""
    import sqlite3
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("DELETE FROM jobs WHERE state='running'")
    if kind == "scan":
        c.execute("""INSERT INTO jobs(kind,state,total,done,started_at,message)
                     VALUES ('scan','running',60,37,?,?)""",
                  (db.now() - 40, job_msg("scan.count", files=37, dirs=4)))
    elif kind == "loop":
        c.execute("""INSERT INTO jobs(kind,state,total,done,started_at,message)
                     VALUES ('download-loop','running',18,11,?,?)""",
                  (db.now() - 90, job_msg("loop.saved", n=2, got=11,
                                          total=18, full="")))
    c.close()


def finish_state(path: Path) -> None:
    """Финальный кадр: часть коллекции доспасена, итоги изменились."""
    import sqlite3
    c = sqlite3.connect(path, isolation_level=None)
    rows = c.execute(
        """SELECT r.path, r.size, r.md5, r.sha256, r.name FROM resources r
           WHERE r.type='file' AND r.path NOT IN (SELECT path FROM local)
           ORDER BY r.path LIMIT 6""").fetchall()
    for cloud_path, size, md5, sha, name in rows:
        local_file = DEMO / "files" / name
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_bytes(b"demo")
        c.execute("""INSERT INTO local(path,local_path,bytes,sha256,md5,
                     verify,downloaded_at,released,missing)
                     VALUES (?,?,?,?,?,'ok',?,0,0)""",
                  (cloud_path, str(local_file), size, sha, md5, db.now() - 60))
    c.close()


def screenshot(page: Page, dest: Path) -> None:
    res = page.send("Page.captureScreenshot", format="png",
                    captureBeyondViewport=False)
    dest.write_bytes(base64.b64decode(res["result"]["data"]))


def wait_render(page: Page, seconds: float = 2.0) -> None:
    time.sleep(seconds)


def js(page: Page, expr: str):
    return page.js(expr)


def take(page: Page, index: int, frames_dir: Path,
         shots: list[Path]) -> None:
    """Снять один экран после принудительного обновления итогов."""
    dest = frames_dir / f"frame_{index:02d}.png"
    wait_render(page, 1.6)
    js(page, "(async () => { await refreshState(true); return 1; })()")
    js(page, CLEAN_JS)
    screenshot(page, dest)
    shots.append(dest)


def build_gif(frames: list[Path], dest: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("нужен ffmpeg в PATH")
    pattern = str(frames[0].parent / "frame_%02d.png")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", "0.5",
           "-i", pattern,
           "-filter_complex",
           ("[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=3"),
           "-loop", "0", str(dest)]
    subprocess.run(cmd, check=True)
    print(f"  {dest.name}: {dest.stat().st_size // 1024} КБ")


def main() -> int:
    ap = argparse.ArgumentParser(description="Демо-гифки на синтетической базе")
    ap.add_argument("--langs", default=",".join(LANGS))
    args = ap.parse_args()
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    edge = next((p for p in EDGE_CANDIDATES if Path(p).is_file()), None)
    if edge is None:
        print("Edge не найден -- съёмка невозможна")
        return 1
    if shutil.which("ffmpeg") is None:
        print("ffmpeg не найден -- съёмка невозможна")
        return 1

    DEMO.mkdir(parents=True, exist_ok=True)
    db_path = DEMO / "catalog.db"
    reset_db(db_path)

    port, cdp = free_port(), free_port()
    env = dict(os.environ, DRYDOCK_ROOT=str(DEMO),
               DRYDOCK_SECRETS=str(DEMO / "secrets.bin"),
               # Сверка зеркала принимала фиктивные файлы за ручные переносы
               # и портила дерево прямо во время съёмки.
               DRYDOCK_LOCAL_SYNC_DELAY="3600", DRYDOCK_LOCAL_SYNC="3600",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "drydock.cli", "serve", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    profile = DEMO / "edge-profile"
    browser = None
    page = None
    try:
        if not wait_http(f"http://127.0.0.1:{port}/api/state"):
            print("сервер не поднялся")
            return 1
        browser = subprocess.Popen(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             f"--window-size={WIDTH},{HEIGHT}",
             f"--remote-debugging-port={cdp}",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_http(f"http://127.0.0.1:{cdp}/json/version"):
            print("браузер не поднялся")
            return 1
        with urllib.request.urlopen(f"http://127.0.0.1:{cdp}/json/list") as resp:
            target = next(t for t in json.load(resp) if t["type"] == "page")
        page = Page(target["webSocketDebuggerUrl"])
        page.send("Page.enable")
        page.send("Runtime.enable")
        page.send("Emulation.setDeviceMetricsOverride", width=WIDTH,
                  height=HEIGHT, deviceScaleFactor=1, mobile=False)
        page.send("Page.addScriptToEvaluateOnNewDocument", source=INIT_JS)
        page.send("Page.navigate", url=f"http://127.0.0.1:{port}/")
        for _ in range(80):
            if js(page, "typeof setLang === 'function' && "
                        "typeof lastState !== 'undefined' && lastState !== null"):
                break
            time.sleep(0.25)
        else:
            print("интерфейс не загрузился")
            return 1
        wait_render(page, 2.0)

        for lang in langs:
            # Каждый язык снимаем на одном и том же начальном состоянии.
            reset_db(db_path)
            frames_dir = DEMO / "frames" / lang
            frames_dir.mkdir(parents=True, exist_ok=True)
            js(page, f"(async () => {{ await setLang('{lang}'); return 1; }})()")
            wait_render(page, 1.5)
            shots: list[Path] = []

            # 1. Главный экран.
            js(page, "closeModal(); closeTools(); "
                     "document.querySelectorAll('.node.sel').forEach("
                     "n => n.classList.remove('sel'));"
                     "$('detail').className = 'detail empty';")
            set_jobs(db_path, None)
            take(page, 1, frames_dir, shots)

            # 2. Опись в работе.
            set_jobs(db_path, "scan")
            take(page, 2, frames_dir, shots)

            # 3. Раскрытая папка и карточка файла.
            set_jobs(db_path, None)
            js(page, """(async () => {
              closeModal();
              expanded.clear();
              await loadTree();
              const side = document.querySelector('.pane.side');
              side.insertBefore($('detail'), side.firstChild);
              const twisty = (p) => {
                const row = document.querySelector(
                  '.node[data-path="' + CSS.escape(p) + '"]');
                if (!row) return false;
                row.querySelector('.twisty').click();
                return true;
              };
              twisty('disk:/Library');
              await new Promise(r => setTimeout(r, 700));
              twisty('disk:/Library/Textbooks');
              await new Promise(r => setTimeout(r, 700));
              const f = document.querySelector(
                '.node[data-path="disk:/Library/Textbooks/Algebra.pdf"]');
              if (f) f.click();
              await new Promise(r => setTimeout(r, 400));
              side.scrollTop = 0;
              return !!f;
            })()""")
            take(page, 3, frames_dir, shots)

            # 4. Выгрузка / круг.
            js(page, "closeModal(); $('detail').className = 'detail hidden';")
            set_jobs(db_path, "loop")
            take(page, 4, frames_dir, shots)

            # 5. Архив.
            set_jobs(db_path, None)
            js(page, "(async () => { await archiveModal(); return 1; })()")
            take(page, 5, frames_dir, shots)

            # 6. Удаление из облака: все три режима.
            js(page, "closeModal(); sel.files.add('disk:/Photos/Frame-001.jpg'); "
                     "refreshSelection(); "
                     "(async () => { await cloudDeleteChoose(); return 1; })()")
            take(page, 6, frames_dir, shots)

            # 7. Финальный экран с обновлёнными итогами.
            finish_state(db_path)
            js(page, """(async () => {
              closeModal();
              sel.files.clear(); sel.folders.clear();
              expanded.clear();
              $('detail').className = 'detail empty';
              await loadTree();
              refreshSelection();
              return 1;
            })()""")
            take(page, 7, frames_dir, shots)

            build_gif(shots, OUT / f"demo.{lang}.gif")
        return 0
    finally:
        if page is not None:
            page.close()
        if browser is not None:
            browser.terminate()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
