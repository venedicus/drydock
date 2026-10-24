"""Настройки Drydock: куда спасаем, чем и с какой осторожностью.

Токен НИКОГДА не печатается в логи и не отдаётся в web UI: наружу уходит
только признак "токен есть/нет" и список выданных прав.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

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
_BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home())
SETTINGS_FILE = _BASE / "Drydock" / "settings.json"
# Прежнее имя проекта: настройки, выбранные до переименования, не теряем.
_LEGACY_SETTINGS = _BASE / "CloudRecovery" / "settings.json"


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


# Очередь выбора корня: переменная окружения (разовый запуск, отладка) ->
# выбор человека в окне -> значение по умолчанию.
SAVE_ROOT = Path(os.environ.get("DRYDOCK_ROOT")
                 or settings().get("save_root")
                 or str(_default_root()))

API = "https://cloud-api.yandex.net/v1/disk"

# 8 потоков -- столько брал автор yandexdl, чтобы не добивать и без того
# раненые сервера Яндекса. Для ВЫГРУЗКИ это верно: там идут мегабайты.
# Сколько файлов качать одновременно. Замеры альтернативного инструмента
# (yandex-disk-rescue, 64 потока): ~0.8 МБ/с на поток, до 33 МБ/с всего.
# 8 потоков -- это ~6 МБ/с потолка, 16 -- вдвое выше; на живых узлах
# очередь узкая, а файлы на некоторых узлах успевают умереть, пока ждут.
CONCURRENCY = int(os.environ.get("DRYDOCK_CONCURRENCY", "16"))

# Проба -- другое дело: это два-три запроса по одному байту, трафика нет
# совсем. На восьми потоках полный проход по 24 тысячам файлов занимал час,
# и к его концу начало успевало протухнуть -- проверка догоняла собственный
# хвост. Здесь узкое место именно наше, поэтому лимит отдельный.
PROBE_CONCURRENCY = int(os.environ.get("DRYDOCK_PROBE_CONCURRENCY", "24"))

# Проверять ли у пробы ещё и ПОСЛЕДНИЙ байт файла. Первый байт отдаётся у
# обрезанных файлов: «Конспект лекций по ТАУ.pdf» проходил пробу, а
# выгрузка умирала на 51910 из 1244840. Второй байт ловит этот класс,
# но стоит лишнего запроса на файл. Мелким файлам он не нужен: их выгрузка
# и так мгновенная, а обрез виден сразу. Выключается
# переменной DRYDOCK_PROBE_TAIL=0, если скорость важнее точности.
PROBE_TAIL = os.environ.get("DRYDOCK_PROBE_TAIL", "1") not in ("0", "false", "no")
# С какого размера проверять хвост. Мельче -- только первый байт.
PROBE_TAIL_MIN = int(os.environ.get("DRYDOCK_PROBE_TAIL_MIN", str(64 * 1024)))

# Как часто сверять зеркало с диском. Обход 7,8 тыс. файлов в 17 тыс.
# папок -- 1.4 секунды (без stat: размер нужен только новым файлам),
# поэтому системный наблюдатель не нужен. 60 секунд -- это ~1% ядра.
LOCAL_SYNC_SECONDS = float(os.environ.get("DRYDOCK_LOCAL_SYNC", "60"))

# Автопилот: сам перепроверяет недоступное и забирает ожившее.
# Годичный замер на нашем аккаунте (18 октября): за пару часов из
# «доступных» выпадало 21%, а 71 файл умирал между пробой и скачиванием.
# Один проход такое не лечит -- лечит повтор. Раз в два часа, круг
# ограничен, чтобы не жечь ночью квоту API.
AUTOPILOT_INTERVAL_H = float(os.environ.get("DRYDOCK_AUTOPILOT_INTERVAL", "2"))
AUTOPILOT_BATCH = int(os.environ.get("DRYDOCK_AUTOPILOT_BATCH", "400"))

# Сколько результат пробы считается свежим. Доступность в облаке плавает:
# файл, не отдавшийся днём, вечером выгружается нормально. Поэтому "ok" --
# это не свойство файла, а наблюдение с датой; после этого срока оно
# показывается как устаревшее и просится на перепроверку.
# Сколько дней хранить историю проб. Она нужна отчёту и «ожило», но
# растёт на 26 тыс. строк за проход: без чистки это миллионы строк в год.
HISTORY_KEEP_DAYS = int(os.environ.get("DRYDOCK_HISTORY_KEEP_DAYS", "90"))

# Как часто фон пересчитывает итоги для интерфейса. Сами итоги стоят
# около 370 мс по 26 тыс. строк -- в обработчике запроса это заметно.
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

# Проба доступности: мёртвый файл висит и отдаёт 504 примерно через 10 минут.
# Ждать столько на каждый файл нельзя -- 25 секунд хватает, чтобы живой
# сервер отдал первый байт, а мёртвый ушёл в таймаут.
PROBE_TIMEOUT = float(os.environ.get("DRYDOCK_PROBE_TIMEOUT", "15"))
DOWNLOAD_TIMEOUT = float(os.environ.get("DRYDOCK_DOWNLOAD_TIMEOUT", "120"))

# Сколько тишины в потоке выгрузки означает, что соединение мертво.
# 120 секунд на один мёртвый файл -- это восемь минут простоя на порцию
# из четырёх: хранилище рвёт передачу часто, и ждать дважды незачем.
DOWNLOAD_READ_TIMEOUT = float(
    os.environ.get("DRYDOCK_DOWNLOAD_READ_TIMEOUT", "40"))

# Сколько раз пробовать один файл ЗА ЗАДАЧУ. Каждая попытка берёт свежую
# ссылку -- то есть, возможно, другую машину хранилища -- и продолжает с
# места обрыва. 18 октября без этого 67 файлов из 250 остались
# недокачанными до ручного перезапуска задачи.
DOWNLOAD_ATTEMPTS = int(os.environ.get("DRYDOCK_DOWNLOAD_ATTEMPTS", "5"))

# Сколько ждать ПЕРВЫЙ байт и каждый следующий кусок. Это не то же самое,
# что DOWNLOAD_TIMEOUT: тот ограничивает запрос целиком, а здесь предел на
# МОЛЧАНИЕ. Живая машина хранилища начинает слать сразу; мёртвая отдаёт
# кусок и замолкает, и без этого предела мы честно ждали общий таймаут.
# Замер 19 октября: 2496 провалов за 3ч12м -- 74 секунды рабочего времени
# на один мёртвый файл, и больше половины из них -- именно молчание.
DOWNLOAD_FIRST_BYTE_S = float(os.environ.get("DRYDOCK_FIRST_BYTE", "12"))
DOWNLOAD_STALL_S = float(os.environ.get("DRYDOCK_STALL", "15"))

# Круговой режим: своя параллельность и одна попытка на файл за круг.
# Повторять внутри круга незачем -- круг и есть повтор, он вернётся к
# этому файлу сам. 19 октября 1513 обрезанных файлов сожгли по ДВЕ
# попытки каждый и не дали ни одного байта.
LOOP_CONCURRENCY = int(os.environ.get("DRYDOCK_LOOP_CONCURRENCY", "48"))
LOOP_ATTEMPTS = int(os.environ.get("DRYDOCK_LOOP_ATTEMPTS", "1"))
# Как часто круг перепроверяет файлы в состоянии gone (404 GoneError).
# Gone -- это ответ API «ресурса нет», а не больная машина хранилища:
# 20 октября 20 418 файлов из 26 785 стояли в gone, и круг тратил на них
# каждый раунд. Раз в сутки -- на случай, если Яндекс ресурсы вернёт.
GONE_RECHECK_S = int(os.environ.get("DRYDOCK_GONE_RECHECK",
                                    str(24 * 3600)))
# Не возвращаться к только что провалившемуся файлу в следующем же круге.
LOOP_COOLDOWN_MIN = float(os.environ.get("DRYDOCK_LOOP_COOLDOWN", "20"))

# Опись: страница папки на 500 элементов -- ответ в пару мегабайт, и на
# раненом облаке 25 секунд ему мало. Запрос уходил в таймаут, лечился
# ретраями, и часовой обход выглядел зависшим на несколько минут. Первый
# байт пробы приходит быстро -- ей 25 хватает, списку folder нет.
API_TIMEOUT = float(os.environ.get("DRYDOCK_API_TIMEOUT", "60"))

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
