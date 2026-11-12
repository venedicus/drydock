"""Настройки Drydock: куда спасаем, чем и с какой осторожностью.

Токен НИКОГДА не печатается в логи и не отдаётся в web UI: наружу уходит
только признак "токен есть/нет" и список выданных прав.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import hostos

# Корень спасённого по умолчанию. Внутри:
#   files/     -- зеркало облака, структура ОДИН В ОДИН
#   meta/      -- превью и опись (то, что спасаем даже для битых файлов)
#   archives/  -- 7z-тома под Телеграм
#   catalog.db -- состояние: что описано, что проверено, что скачано, что в архиве
# Куда спасать по умолчанию. Рядом с домашней папкой, без чужих путей:
# конкретное место человек выбирает в интерфейсе, и оно запоминается.
DEFAULT_SAVE_ROOT = Path.home() / "YandexDiskSaved"

# Прежний путь по умолчанию: у кого программа уже работала, данные лежат
# там. Если нового каталога ещё нет, а старый есть -- продолжаем в нём,
# чтобы обновление не начинало с пустого места.
_LEGACY_DEFAULT_ROOT = Path.home() / "Desktop" / "YandexDiskSaved"


def _default_root() -> Path:
    if not DEFAULT_SAVE_ROOT.exists() and _LEGACY_DEFAULT_ROOT.exists():
        return _LEGACY_DEFAULT_ROOT
    return DEFAULT_SAVE_ROOT
# Выбор человека -- отдельным файлом рядом с лаунчером: он переживает и
# venv, и переустановку зависимостей, и git checkout.


def settings_file() -> Path:
    """Файл настроек. В тестах изолируется через DRYDOCK_SETTINGS или DRYDOCK_ROOT."""
    if os.environ.get("DRYDOCK_SETTINGS"):
        return Path(os.environ["DRYDOCK_SETTINGS"])
    if os.environ.get("DRYDOCK_ROOT"):
        return Path(os.environ["DRYDOCK_ROOT"]) / "settings.json"
    return hostos.app_dir() / "settings.json"


# Прежнее имя проекта: настройки, выбранные до переименования, не теряем.
_LEGACY_SETTINGS = hostos.legacy_app_dir() / "settings.json"
SETTINGS_FILE = settings_file()


def settings() -> dict:
    """Что человек выбрал в интерфейсе (пока -- только корень)."""
    for path in (SETTINGS_FILE, _LEGACY_SETTINGS):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def inspect_db(db_path: Path | str) -> dict | None:
    """Проверить, является ли файл базой Drydock, и вернуть сводку."""
    p = Path(db_path)
    try:
        if not p.is_file() or p.stat().st_size < 100:
            return None
        import sqlite3
        conn = sqlite3.connect(p, timeout=1.0)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "resources" not in tables:
                return None
            files_cnt = conn.execute(
                "SELECT COUNT(*) FROM resources WHERE type='file'").fetchone()[0]
            saved_cnt = 0
            if "local" in tables:
                saved_cnt = conn.execute(
                    "SELECT COUNT(*) FROM local WHERE verify='ok'").fetchone()[0]
            root = p.parent
            return {
                "root": str(root),
                "db_path": str(p),
                "files_count": int(files_cnt or 0),
                "saved_count": int(saved_cnt or 0),
                "db_size": int(p.stat().st_size),
                "last_modified": int(p.stat().st_mtime),
                "has_files": (root / "files").is_dir(),
                "has_archives": (root / "archives").is_dir(),
            }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def record_known_root(path: Path | str) -> None:
    """Запомнить путь к папке сохранения в истории."""
    p_str = str(Path(path))
    data = settings()
    roots = data.get("known_roots", [])
    if not isinstance(roots, list):
        roots = []
    if p_str in roots:
        roots.remove(p_str)
    roots.insert(0, p_str)
    data["known_roots"] = roots[:15]
    db_file = Path(path) / "catalog.db"
    if db_file.is_file():
        data["last_known_db"] = str(db_file)
    save_settings(data)


def known_roots() -> list[str]:
    data = settings()
    roots = []
    raw = data.get("known_roots")
    if isinstance(raw, list):
        roots.extend(str(r) for r in raw if r)
    curr = data.get("save_root")
    if curr and curr not in roots:
        roots.insert(0, str(curr))
    for def_root in (DEFAULT_SAVE_ROOT, _LEGACY_DEFAULT_ROOT, Path.home() / "Documents" / "YandexDiskSaved"):
        s = str(def_root)
        if s not in roots:
            roots.append(s)
    return roots


def discover_databases() -> list[dict]:
    """Найти существующие базы Drydock на дисках и в истории."""
    candidates: list[Path] = []
    for r in known_roots():
        candidates.append(Path(r) / "catalog.db")
    import string
    system_drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    for drv in system_drives:
        d_path = Path(drv)
        for sub in ("YandexDiskSaved", "Drydock", "CloudRecovery"):
            candidates.append(d_path / sub / "catalog.db")
        if drv.upper() != "C:\\":
            try:
                for entry in os.scandir(drv):
                    if entry.is_dir():
                        candidates.append(Path(entry.path) / "catalog.db")
                        candidates.append(Path(entry.path) / "YandexDiskSaved" / "catalog.db")
            except OSError:
                pass
    seen_resolved: set[str] = set()
    found: list[dict] = []
    for cand in candidates:
        try:
            res_str = str(cand.resolve()) if cand.exists() else str(cand)
        except OSError:
            res_str = str(cand)
        if res_str in seen_resolved:
            continue
        seen_resolved.add(res_str)
        info = inspect_db(cand)
        if info:
            found.append(info)
    found.sort(key=lambda x: (x["files_count"] > 0, x["last_modified"]), reverse=True)
    return found
# Очередь выбора корня: переменная окружения (разовый запуск, отладка) ->
# выбор человека в окне -> значение по умолчанию.
SAVE_ROOT = Path(os.environ.get("DRYDOCK_ROOT")
                 or settings().get("save_root")
                 or str(_default_root()))
API = "https://cloud-api.yandex.net/v1/disk"

# Сколько файлов качать одновременно. Широкая очередь на повреждённом
# хранилище не ускоряет выгрузку: часть узлов отдаёт 429, а файлы успевают
# умереть, пока ждут.
CONCURRENCY = int(os.environ.get("DRYDOCK_CONCURRENCY", "16"))

# Проба -- короткие запросы почти без трафика, поэтому лимит отдельный:
# при узкой очереди проверка не поспевает за собственным хвостом.
PROBE_CONCURRENCY = int(os.environ.get("DRYDOCK_PROBE_CONCURRENCY", "24"))

# Проверять ли у пробы ещё и ПОСЛЕДНИЙ байт файла: у обрезанных
# первый байт отдаётся. Это лишний запрос на файл, поэтому для мелких
# файлов хвост не проверяется. Отключается DRYDOCK_PROBE_TAIL=0.
PROBE_TAIL = os.environ.get("DRYDOCK_PROBE_TAIL", "1") not in ("0", "false", "no")

# С какого размера проверять хвост. Мельче -- только первый байт.
PROBE_TAIL_MIN = int(os.environ.get("DRYDOCK_PROBE_TAIL_MIN", str(64 * 1024)))

# Как часто сверять зеркало с диском. Обход дешёвый: размер нужен только
# новым файлам, поэтому системный наблюдатель не требуется.
LOCAL_SYNC_SECONDS = float(os.environ.get("DRYDOCK_LOCAL_SYNC", "60"))
# Первый проход -- не сразу после старта: обход зеркала занимает диск на
# десятки секунд, а окно в это время только открывается.
LOCAL_SYNC_FIRST_DELAY = float(os.environ.get("DRYDOCK_LOCAL_SYNC_DELAY", "15"))

# Автопилот: сам перепроверяет недоступное и забирает ожившее.
# Доступность плавает, поэтому один проход ничего не решает -- решает
# повтор по расписанию. Круг ограничен, чтобы не жечь квоту API.
AUTOPILOT_INTERVAL_H = float(os.environ.get("DRYDOCK_AUTOPILOT_INTERVAL", "2"))
AUTOPILOT_BATCH = int(os.environ.get("DRYDOCK_AUTOPILOT_BATCH", "400"))

# Таймаут круга: на деградирующем хранилище круг часто ничего не спасает
# («ожило 0»). Гонять его по обычному расписанию бессмысленно -- это только
# жжёт квоту API и мешает живой работе. Поэтому пустой круг откладывается
# на короткую паузу, а после нескольких пустых подряд -- на длинную.
#
# idle (пустой) круг -- тот, где revived <= AUTOPILOT_IDLE_REVIVED_MAX. Точечная
# настройка: каждый порог -- отдельная переменная окружения ИЛИ поле в
# settings.json (ключ autopilot_config), что выбрано в интерфейсе.
AUTOPILOT_IDLE_REVIVED_MAX = int(
    os.environ.get("DRYDOCK_AUTOPILOT_IDLE_REVIVED_MAX", "0"))
# Короткая пауза после пустого круга -- «попробовать ещё раз через 5 минут».
# 0 -- перепроверять сразу (круг повторится при следующем опросе, ~60 с).
AUTOPILOT_IDLE_COOLDOWN_MIN = float(
    os.environ.get("DRYDOCK_AUTOPILOT_IDLE_COOLDOWN", "5"))
# Длинная пауза после AUTOPILOT_IDLE_STEPS пустых кругов подряд -- «раз в час».
# 0 -- и здесь сразу, без длинной паузы.
AUTOPILOT_IDLE_LONG_MIN = float(
    os.environ.get("DRYDOCK_AUTOPILOT_IDLE_COOLDOWN_LONG", "60"))
# Сколько пустых кругов подряд, прежде чем перейти на длинную паузу.
# 12 * 5 мин = 60 мин -- плавный переход «5 минут -> раз в час».
AUTOPILOT_IDLE_STEPS = int(
    os.environ.get("DRYDOCK_AUTOPILOT_IDLE_STEPS", "12"))

# Тот же тайминг для КРУГОВ ВЫГРУЗКИ (download.run_rounds): круг, в котором
# не спасено ничего, раньше повторялся через жёсткие 60 с -- в логах за
# 07.11 это круги 50..65 подряд с «спасено 0». Настройка одна на оба вида
# кругов, чтобы человеку не приходилось помнить, какой из них где.
LOOP_PAUSE_S = int(os.environ.get("DRYDOCK_LOOP_PAUSE", "300"))
LOOP_PAUSE_LONG_S = int(os.environ.get("DRYDOCK_LOOP_PAUSE_LONG", "3600"))
LOOP_PAUSE_STEPS = int(os.environ.get("DRYDOCK_LOOP_PAUSE_STEPS", "12"))

# Ключи точечной настройки кругов, которые человек может задать в
# интерфейсе (через settings.json). Значения ограничены этим списком,
# чтобы POST /api/rounds/config не перезаписал лишнего.
AUTOPILOT_CONFIG_KEYS = (
    "hours", "batch",
    "idle_revived_max", "idle_cooldown_min", "idle_long_min", "idle_steps",
    "loop_pause_s", "loop_pause_long_s", "loop_pause_steps",
)


def autopilot_config() -> dict:
    """Действующая настройка автопилота.

    Приоритет: переменные окружения (константы выше) -> autopilot_config из
    settings.json (что выбрано в интерфейсе) -> умолчания. Так одно и то же
    поле точечно переопределяется без правки кода и перезапуска не требует
    правки окружения.
    """
    data = settings().get("autopilot_config")
    if not isinstance(data, dict):
        data = {}
    cfg = {
        "hours": AUTOPILOT_INTERVAL_H,
        "batch": AUTOPILOT_BATCH,
        "idle_revived_max": AUTOPILOT_IDLE_REVIVED_MAX,
        "idle_cooldown_min": AUTOPILOT_IDLE_COOLDOWN_MIN,
        "idle_long_min": AUTOPILOT_IDLE_LONG_MIN,
        "idle_steps": AUTOPILOT_IDLE_STEPS,
        "loop_pause_s": LOOP_PAUSE_S,
        "loop_pause_long_s": LOOP_PAUSE_LONG_S,
        "loop_pause_steps": LOOP_PAUSE_STEPS,
    }
    # Точечное переопределение из settings.json -- привести к нужному типу.
    for key, default in cfg.items():
        if key in data and data[key] not in (None, ""):
            try:
                cfg[key] = type(default)(data[key])
            except (TypeError, ValueError):
                pass
    # Отрицательная пауза -- это «сразу» (0). Ноль допустим везде: человек
    # вправе выключить задержку altogether и перепроверять каждый круг.
    for key, value in cfg.items():
        if isinstance(value, (int, float)) and value < 0:
            cfg[key] = type(value)(0)
    return cfg


def autopilot_cooldown_seconds(idle_streak: int,
                              cfg: dict | None = None) -> float:
    """Сколько секунд ждать до следующего круга.

    idle_streak == 0 -- обычный интервал (hours). >0 -- прошлый круг был
    пустым: короткая пауза, а после idle_steps пустых подряд -- длинная.
    Любая пауза может быть 0 -- тогда круг повторится при следующем опросе
    петли (раз в ~60 с). Отрицательные значения тоже трактуем как 0.
    """
    cfg = cfg or autopilot_config()

    def pause(key: str, scale: float) -> float:
        return max(0.0, float(cfg[key])) * scale

    if not idle_streak or idle_streak <= 0:
        return pause("hours", 3600.0)
    steps = max(1, int(cfg["idle_steps"]))
    if idle_streak < steps:
        return pause("idle_cooldown_min", 60.0)
    return pause("idle_long_min", 60.0)


def loop_pause_seconds(empty_streak: int, cfg: dict | None = None) -> int:
    """Пауза между кругами выгрузки, в которых не спасено ничего.

    Та же лестница, что у автопилота: короткая пауза, а после
    loop_pause_steps пустых кругов подряд -- длинная. 0 -- «сразу» (круг
    повторится без ожидания). Отрицательные значения тоже трактуем как 0.
    """
    cfg = cfg or autopilot_config()
    if not empty_streak or empty_streak <= 0:
        return 0
    steps = max(1, int(cfg["loop_pause_steps"]))
    key = "loop_pause_s" if empty_streak < steps else "loop_pause_long_s"
    return max(0, int(float(cfg[key])))


# Готовые варианты для карточки на главном экране. Один клик задаёт СРАЗУ
# оба вида кругов -- человеку не надо знать, что их два. «Постепенно» -- это
# умолчания: 5 минут, а после 12 пустых подряд -- час.
ROUND_PRESETS: dict[str, dict] = {
    "now": {"hours": 0, "idle_cooldown_min": 0, "idle_long_min": 0,
            "idle_steps": 1, "loop_pause_s": 0, "loop_pause_long_s": 0,
            "loop_pause_steps": 1, "idle_revived_max": 0},
    "m5": {"hours": 2, "idle_cooldown_min": 5, "idle_long_min": 5,
           "idle_steps": 1, "loop_pause_s": 300, "loop_pause_long_s": 300,
           "loop_pause_steps": 1, "idle_revived_max": 0},
    "h1": {"hours": 2, "idle_cooldown_min": 60, "idle_long_min": 60,
           "idle_steps": 1, "loop_pause_s": 3600, "loop_pause_long_s": 3600,
           "loop_pause_steps": 1, "idle_revived_max": 0},
    "gradual": {"hours": 2, "idle_cooldown_min": 5, "idle_long_min": 60,
                "idle_steps": 12, "loop_pause_s": 300,
                "loop_pause_long_s": 3600, "loop_pause_steps": 12,
                "idle_revived_max": 0},
}


def apply_round_preset(name: str) -> dict:
    """Сохранить готовый вариант и вернуть действующую настройку.

    Возвращает пустой dict для неизвестного имени -- вызывающий проверит
    это и отдаст 400, а не молча сотрёт настройку.
    """
    preset = ROUND_PRESETS.get(name)
    if not preset:
        return {}
    data = settings()
    cur = data.get("autopilot_config")
    if not isinstance(cur, dict):
        cur = {}
    # Прессет задаёт только тайминг; batch и прочие поля не трогаем.
    cur.update(preset)
    data["autopilot_config"] = cur
    save_settings(data)
    return autopilot_config()

# Сколько результат пробы считается свежим. «Доступно» -- не свойство
# файла, а наблюдение с датой: после срока оно показывается как устаревшее
# и просится на перепроверку.
# История проб нужна отчёту и «ожило», но растёт с каждым проходом --
# без чистки это миллионы строк в год.
HISTORY_KEEP_DAYS = int(os.environ.get("DRYDOCK_HISTORY_KEEP_DAYS", "90"))

# Порт окна по умолчанию. Меняется в настройках или переменной окружения;
# аргумент командной строки --port сильнее обоих.
DEFAULT_PORT = 8765


def port() -> int:
    """Порт из настроек или окружения. Некорректный -- молча по умолчанию."""
    raw = os.environ.get("DRYDOCK_PORT") or settings().get("port")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return value if 1024 <= value <= 65535 else DEFAULT_PORT
TOTALS_REFRESH_S = float(os.environ.get("DRYDOCK_TOTALS_REFRESH", "15"))
PROBE_TTL_HOURS = float(os.environ.get("DRYDOCK_PROBE_TTL", "12"))

# Проба доступности: мёртвый файл висит и отдаёт 504 минутами. Ждать
# столько на каждый файл нельзя; живому серверу хватает нескольких секунд.
PROBE_TIMEOUT = float(os.environ.get("DRYDOCK_PROBE_TIMEOUT", "15"))
DOWNLOAD_TIMEOUT = float(os.environ.get("DRYDOCK_DOWNLOAD_TIMEOUT", "120"))

# Сколько тишины в потоке выгрузки означает, что соединение мертво.
# Ждать общий таймаут дважды незачем: хранилище рвёт передачу часто.
DOWNLOAD_READ_TIMEOUT = float(
    os.environ.get("DRYDOCK_DOWNLOAD_READ_TIMEOUT", "40"))
# Сколько раз пробовать один файл ЗА ЗАДАЧУ. Каждая попытка берёт свежую
# ссылку -- возможно, другую машину хранилища -- и продолжает с места
# обрыва, поэтому без повторов часть файлов остаётся недокачанной.
DOWNLOAD_ATTEMPTS = int(os.environ.get("DRYDOCK_DOWNLOAD_ATTEMPTS", "5"))

# Сколько ждать ПЕРВЫЙ байт и каждый следующий кусок. Это не то же самое,
# что DOWNLOAD_TIMEOUT: тот ограничивает запрос целиком, а здесь предел на
# МОЛЧАНИЕ. Живая машина хранилища начинает слать сразу; мёртвая отдаёт
# кусок и замолкает.
DOWNLOAD_FIRST_BYTE_S = float(os.environ.get("DRYDOCK_FIRST_BYTE", "12"))
DOWNLOAD_STALL_S = float(os.environ.get("DRYDOCK_STALL", "15"))

# Круговой режим: своя параллельность и одна попытка на файл за круг.
# Повторять внутри круга незачем -- круг и есть повтор, он вернётся к
# этому файлу сам.
LOOP_CONCURRENCY = int(os.environ.get("DRYDOCK_LOOP_CONCURRENCY", "48"))
LOOP_ATTEMPTS = int(os.environ.get("DRYDOCK_LOOP_ATTEMPTS", "1"))

# Как часто круг перепроверяет файлы в состоянии gone (404 GoneError).
# Gone -- это ответ API «ресурса нет», а не больная машина хранилища:
# тратить на них каждый раунд бессмысленно. Раз в сутки -- на случай,
# если ресурсы вернутся.
GONE_RECHECK_S = int(os.environ.get("DRYDOCK_GONE_RECHECK",
                                    str(24 * 3600)))
# Не возвращаться к только что провалившемуся файлу в следующем же круге.
LOOP_COOLDOWN_MIN = float(os.environ.get("DRYDOCK_LOOP_COOLDOWN", "20"))

# Опись: страница папки -- ответ в пару мегабайт, и на раненом облаке
# общего таймаута ему не хватает: запрос уходил в ретраи, и обход выглядел
# зависшим. Пробе хватает меньшего -- ей нужен первый байт.
API_TIMEOUT = float(os.environ.get("DRYDOCK_API_TIMEOUT", "60"))

# Сколько папок опись перечисляет одновременно. Ожидание ответа на
# каждую папку оставляет сеть без работы; выше лимита API отдаёт 429,
# а _api умеет ждать Retry-After.
SCAN_CONCURRENCY = int(os.environ.get("DRYDOCK_SCAN_CONCURRENCY", "8"))

# Пропускать ли при описи папки, которые в прошлый раз оказались пустыми
# и с тех пор не менялись. Пустая папка обходится одним запросом и не
# даёт ничего, а в коллекции их тысячи -- и именно они съедали время
# описи. Выключается, когда нужна полная перепроверка облака.
SCAN_SKIP_EMPTY = os.environ.get("DRYDOCK_SCAN_SKIP_EMPTY", "1") not in (
    "0", "false", "no")
# Архивация: тома под Телеграм-премиум (лимит 4 ГБ, берём 3900 МБ).
VOLUME = os.environ.get("DRYDOCK_VOLUME", "3900m")

# -mx0: книги и так сжаты, а предсказуемый размер тома важнее процентов.
COMPRESSION = os.environ.get("DRYDOCK_COMPRESSION", "-mx0")

# Запас места, который архивация не трогает никогда.
RESERVE = int(os.environ.get("DRYDOCK_RESERVE", str(5 * 1024**3)))
PREVIEW_SIZE = "XXXL"
BLOCK = 1024 * 1024  # шаг чтения и шаг salvage-режима


@dataclass(frozen=True)


class Paths:
    root: Path
    @property
    def files(self) -> Path:
        return self.root / "files"
    @property
    def meta(self) -> Path:
        return self.root / "meta"
    @property
    def previews(self) -> Path:
        return self.meta / "previews"
    @property
    def catalog_jsonl(self) -> Path:
        return self.meta / "catalog.jsonl"
    @property
    def archives(self) -> Path:
        return self.root / "archives"
    @property
    def db(self) -> Path:
        return self.root / "catalog.db"
    @property
    def audit(self) -> Path:
        return self.root / "audit.jsonl"
    def ensure(self) -> None:
        for p in (self.root, self.files, self.meta, self.previews, self.archives):
            p.mkdir(parents=True, exist_ok=True)
PATHS = Paths(SAVE_ROOT)


def set_root(path: Path | str) -> None:
    """Переназначить корень спасения.
    Нужно тестам: каждый файл тестов при импорте задаёт свой
    DRYDOCK_ROOT, а PATHS связывается один раз на процесс. Если в
    одном процессе оказалось несколько файлов тестов, они бы поделили один
    корень -- и писали бы в чужую базу.
    """
    global PATHS
    PATHS = Paths(Path(path))
    PATHS.ensure()


def token() -> str | None:
    """Рабочий токен.
    Порядок: шифрованное хранилище (основной путь, умеет продлевать токен
    сам) -> YANDEX_DISK_TOKEN -> <проект>/.env -> <проект>/secrets/token.txt.
    Переменная окружения оставлена для разовых запусков и отладки.
    """
    try:
        from . import oauth
        stored = oauth.access_token()
        if stored:
            return stored
    except (ImportError, OSError, RuntimeError):
        pass
    env = os.environ.get("YANDEX_DISK_TOKEN")
    if env and env.strip():
        return env.strip()
    here = Path(__file__).resolve().parent.parent
    dotenv = here / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("YANDEX_DISK_TOKEN") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    secret = here / "secrets" / "token.txt"
    if secret.is_file():
        val = secret.read_text(encoding="utf-8").strip()
        if val:
            return val
    return None


def require_token() -> str:
    tok = token()
    if not tok:
        raise SystemExit(
            "Нет доступа к Диску. Самый короткий путь:\n"
            "  drydock auth app      -- ввести ClientID и Client secret\n"
            "  drydock auth login    -- открыть страницу согласия\n"
            "Либо то же самое в web UI: кнопка «Доступ». Подробности в README.md."
        )
    return tok
