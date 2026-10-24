"""Словари интерфейса: один источник -- шесть файлов.

Переводы лежат здесь вместе, строка к строке, а не в шести отдельных
JSON-ах. Причина простая: при раздельных файлах они разъезжаются -- строку
добавили в русский, в казахский забыли, и в интерфейсе появляется сырой
ключ. Здесь забыть невозможно: отсутствующий язык виден сразу, а проверка
в tests/test_i18n.py падает, если где-то пусто.

    .venv/Scripts/python tools/make_i18n.py      # пересобрать web/i18n/*.json

Языки: русский (оригинал), английский, турецкий, казахский, узбекский,
азербайджанский -- там, где Яндексом пользуются.

Множественное число: у русского три формы (one/few/many), у остальных две
(one/other). Такие строки записаны словарём форм.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "i18n"
LANGS = ("ru", "en", "tr", "kk", "uz", "az")

S: dict[str, dict[str, object]] = {

    # ── шапка ────────────────────────────────────────────────────────
    "lang.auto": {
        "ru": "Авто (по системе)", "en": "Auto (system)", "tr": "Oto (sistem)",
        "kk": "Авто (жүйе бойынша)", "uz": "Avto (tizim boʻyicha)", "az": "Avto (sistem)",
    },
    "lang.pick": {
        "ru": "Язык интерфейса", "en": "Interface language",
        "tr": "Arayüz dili", "kk": "Интерфейс тілі",
        "uz": "Interfeys tili", "az": "İnterfeys dili",
    },

    # ── единицы ──────────────────────────────────────────────────────
    "unit.b": {"ru": "Б", "en": "B", "tr": "B", "kk": "Б", "uz": "B", "az": "B"},
    "unit.kb": {"ru": "КБ", "en": "KB", "tr": "KB", "kk": "КБ", "uz": "KB", "az": "KB"},
    "unit.mb": {"ru": "МБ", "en": "MB", "tr": "MB", "kk": "МБ", "uz": "MB", "az": "MB"},
    "unit.gb": {"ru": "ГБ", "en": "GB", "tr": "GB", "kk": "ГБ", "uz": "GB", "az": "GB"},
    "unit.tb": {"ru": "ТБ", "en": "TB", "tr": "TB", "kk": "ТБ", "uz": "TB", "az": "TB"},
    "unit.pcs": {"ru": "шт", "en": "pcs", "tr": "adet", "kk": "дана",
                 "uz": "dona", "az": "ədəd"},

    # Слово "файл" при числе. По-русски нужно три формы: 1 файл, 2 файла,
    # 5 файлов. В тюркских после числительного существительное не
    # склоняется -- одна форма на оба случая, но ключи нужны оба.
    "n.files": {
        "ru": {"one": "файл", "few": "файла", "many": "файлов"},
        "en": {"one": "file", "other": "files"},
        "tr": {"one": "dosya", "other": "dosya"},
        "kk": {"one": "файл", "other": "файл"},
        "uz": {"one": "fayl", "other": "fayl"},
        "az": {"one": "fayl", "other": "fayl"},
    },
    "n.folders": {
        "ru": {"one": "папка", "few": "папки", "many": "папок"},
        "en": {"one": "folder", "other": "folders"},
        "tr": {"one": "klasör", "other": "klasör"},
        "kk": {"one": "қалта", "other": "қалта"},
        "uz": {"one": "papka", "other": "papka"},
        "az": {"one": "qovluq", "other": "qovluq"},
    },

    # ── чипы состояния ───────────────────────────────────────────────
    "chip.revived": {
        "ru": "ожило <b>{n}</b>", "en": "came back <b>{n}</b>",
        "tr": "geri döndü <b>{n}</b>", "kk": "қайта оралды <b>{n}</b>",
        "uz": "qaytib keldi <b>{n}</b>", "az": "geri qayıtdı <b>{n}</b>",
    },
    "chip.saveTo": {
        "ru": "спасаем в <b>{path}</b>", "en": "saving to <b>{path}</b>",
        "tr": "kaydedilen yer <b>{path}</b>", "kk": "сақтау орны <b>{path}</b>",
        "uz": "saqlanadi <b>{path}</b>", "az": "saxlanılır <b>{path}</b>",
    },
    "chip.saveTo.title": {
        "ru": "Сюда складывается спасённое, структура как в облаке. Щёлкни, чтобы открыть папку",
        "en": "Rescued files land here, mirroring the cloud structure. Click to open the folder",
        "tr": "Kurtarılanlar buraya, bulut yapısıyla aynı şekilde iner. Klasörü açmak için tıklayın",
        "kk": "Құтқарылғаны осында, бұлттағыдай құрылыммен. Қалтаны ашу үшін басыңыз",
        "uz": "Qutqarilganlar shu yerga, bulutdagi tuzilma bilan tushadi. Papkani ochish uchun bosing",
        "az": "Xilas edilənlər bura, buluddakı strukturla düşür. Qovluğu açmaq üçün klikləyin",
    },
    "detail.localPath": {
        "ru": "лежит здесь", "en": "stored at", "tr": "burada",
        "kk": "мұнда жатыр", "uz": "shu yerda", "az": "buradadır",
    },
    "detail.localMissing": {
        "ru": "файла нет на диске — запись осталась, копии нет",
        "en": "file is missing on disk — the record remains, the copy is gone",
        "tr": "dosya diskte yok — kayıt kaldı, kopya yok",
        "kk": "файл дискіде жоқ — жазба қалды, көшірме жоқ",
        "uz": "fayl diskda yo‘q — yozuv qoldi, nusxa yo‘q",
        "az": "fayl diskdə yoxdur — qeyd qalıb, nüsxə yoxdur",
    },
    "detail.localMissingShort": {
        "ru": "(файла нет на диске)", "en": "(missing on disk)",
        "tr": "(diskte yok)", "kk": "(дискіде жоқ)",
        "uz": "(diskda yo‘q)", "az": "(diskdə yoxdur)",
    },
    "detail.openFolder": {
        "ru": "открыть папку", "en": "open folder", "tr": "klasörü aç",
        "kk": "қалтаны ашу", "uz": "papkani ochish", "az": "qovluğu aç",
    },
    "probe.scope.stale": {
        "ru": "перепроверить устаревшее", "en": "recheck stale",
        "tr": "eskimişleri yeniden denetle", "kk": "ескіргенді қайта тексеру",
        "uz": "eskirganni qayta tekshirish", "az": "köhnəlmişləri yenidən yoxla",
    },
    "detail.ago": {
        "ru": "{n} ч назад", "en": "{n} h ago", "tr": "{n} sa önce",
        "kk": "{n} сағ бұрын", "uz": "{n} soat oldin", "az": "{n} saat əvvəl",
    },
    "detail.staleNote": {
        "ru": "устарело — состояние на момент проверки, не сейчас",
        "en": "stale — state as of the check, not now",
        "tr": "eskimiş — denetim anındaki durum, şu anki değil",
        "kk": "ескірген — тексеру сәтіндегі күй, қазіргі емес",
        "uz": "eskirgan — tekshiruv paytidagi holat, hozirgi emas",
        "az": "köhnəlmiş — yoxlama anındakı vəziyyət, indiki deyil",
    },
    "tree.staleTip": {
        "ru": "устарело {n} из {files}: проверено давно, сейчас может быть иначе",
        "en": "{n} of {files} stale: checked long ago, may differ now",
        "tr": "{files} içinde {n} eskimiş: çok önce denetlendi, şimdi farklı olabilir",
        "kk": "{files} ішінен {n} ескірген: баяғыда тексерілген, қазір басқаша болуы мүмкін",
        "uz": "{files} dan {n} eskirgan: ancha oldin tekshirilgan, hozir boshqacha boʻlishi mumkin",
        "az": "{files} -dan {n} köhnəlmiş: çoxdan yoxlanılıb, indi fərqli ola bilər",
    },
    "chip.unchecked": {
        "ru": "не проверено <b>{n}</b>", "en": "unchecked <b>{n}</b>",
        "tr": "denetlenmedi <b>{n}</b>", "kk": "тексерілмеген <b>{n}</b>",
        "uz": "tekshirilmagan <b>{n}</b>", "az": "yoxlanılmayıb <b>{n}</b>",
    },
    "chip.archives": {
        "ru": "архивов <b>{n}</b> · {size}", "en": "archives <b>{n}</b> · {size}",
        "tr": "arşiv <b>{n}</b> · {size}", "kk": "мұрағат <b>{n}</b> · {size}",
        "uz": "arxiv <b>{n}</b> · {size}", "az": "arxiv <b>{n}</b> · {size}",
    },
    "chip.noToken": {
        "ru": "<b>токена нет</b>", "en": "<b>no token</b>", "tr": "<b>token yok</b>",
        "kk": "<b>токен жоқ</b>", "uz": "<b>token yoʻq</b>", "az": "<b>token yoxdur</b>",
    },
    "chip.tokenDead": {
        "ru": "<b>токен не работает</b> — нужен новый", "en": "<b>token rejected</b> — get a new one",
        "tr": "<b>token reddedildi</b> — yenisi gerek", "kk": "<b>токен қабылданбайды</b> — жаңасы керек",
        "uz": "<b>token rad etildi</b> — yangisi kerak", "az": "<b>token rədd edildi</b> — yenisi lazımdır",
    },
    "chip.no7zip": {
        "ru": "<b>7-Zip не найден</b>", "en": "<b>7-Zip not found</b>",
        "tr": "<b>7-Zip bulunamadı</b>", "kk": "<b>7-Zip табылмады</b>",
        "uz": "<b>7-Zip topilmadi</b>", "az": "<b>7-Zip tapılmadı</b>",
    },

    # ── кнопки ───────────────────────────────────────────────────────
    # ── новый экран: сводка, плитки итогов, легенда, группы палитры ──
    # ── карточка «Что дальше»: по набору на каждый вид шага ──────────
    # Виды задаёт сервер (server.next_step): busy, scan, download, probe,
    # stale, archive, autopilot, done. Забытый вид виден сразу -- в карточке
    # вместо текста появляется сырой ключ, поэтому полноту стережёт тест.
    "next.busy.lead": {
        "ru": "Работа идёт", "en": "Work in progress", "tr": "Calisma suruyor",
        "kk": "Жумыс журiп жатыр", "uz": "Ish davom etmoqda", "az": "Is gedir",
    },
    "next.busy.why": {
        "ru": "Дождись окончания или останови -- тогда появится следующий шаг.",
        "en": "Wait for it to finish or stop it -- the next step appears then.",
        "tr": "Bitmesini bekleyin ya da durdurun -- sonraki adim o zaman gorunur.",
        "kk": "Аяқталуын күтіңіз немесе тоқтатыңыз -- сонда келесі қадам шығады.",
        "uz": "Tugashini kuting yoki toxtating -- keyin navbatdagi qadam chiqadi.",
        "az": "Bitmesini gozleyin ve ya dayandirin -- sonra novbeti addim gorunecek.",
    },
    "next.scan.lead": {
        "ru": "Опись не закончена: в очереди {n}",
        "en": "Inventory unfinished: {n} queued",
        "tr": "Envanter tamamlanmadi: sirada {n}",
        "kk": "Тізім аяқталмаған: кезекте {n}",
        "uz": "Royxat tugallanmagan: navbatda {n}",
        "az": "Siyahi bitmeyib: novbede {n}",
    },
    "next.scan.why": {
        "ru": "Пока облако не описано целиком, не видно, что в нём есть и что уже потеряно.",
        "en": "Until the cloud is fully inventoried, there is no seeing what exists and what is lost.",
        "tr": "Bulut tumuyle envanterlenene kadar neyin var olduğu gorulemez.",
        "kk": "Бұлт толық тізімделмейінше, не бар және не жоғалғаны көрінбейді.",
        "uz": "Bulut toliq royxatga olinmaguncha, nima bor va nima yoqolgani korinmaydi.",
        "az": "Bulud tam siyahiya alinmayana qeder neyin olduğu gorunmur.",
    },
    "next.scan.btn": {
        "ru": "Продолжить опись", "en": "Continue inventory", "tr": "Envantere devam et",
        "kk": "Тізімдеуді жалғастыру", "uz": "Royxatni davom ettirish",
        "az": "Siyahiya davam et",
    },
    "next.download.lead": {
        "ru": "{n} {files} можно забрать прямо сейчас",
        "en": "{n} {files} can be taken right now",
        "tr": "{n} {files} hemen alinabilir",
        "kk": "{n} {files} дәл қазір алуға болады",
        "uz": "{n} {files} hozir olish mumkin",
        "az": "{n} {files} ele indi goturmek olar",
    },
    "next.download.why": {
        "ru": "Доступность гниёт на глазах: что отдаётся сегодня, завтра может уже не отдаться.",
        "en": "Availability is rotting: what serves today may not serve tomorrow.",
        "tr": "Erisilebilirlik curuyor: bugun verilen yarin verilmeyebilir.",
        "kk": "Қолжетімділік көз алдында шіриді: бүгін берілген ертең берілмеуі мүмкін.",
        "uz": "Mavjudlik koz oldida chiriydi: bugun beriladigan ertaga berilmasligi mumkin.",
        "az": "Elcatanliq gozumuzun onunde curuyur: bu gun verilen sabah verilmeye biler.",
    },
    "next.download.btn": {
        "ru": "Скачать доступное", "en": "Download available",
        "tr": "Erisilebilirleri indir", "kk": "Қолжетімдіні жүктеу",
        "uz": "Mavjudni yuklash", "az": "Elcatanlari endir",
    },
    "lens.now": {
        "ru": "Сейчас", "en": "Now", "tr": "Şimdi",
        "kk": "Қазір", "uz": "Hozir", "az": "İndi",
    },
    "lens.now.title": {
        "ru": "Что облако держит прямо сейчас: доступное, недоступное и непроверенное",
        "en": "What the cloud holds right now: available, unavailable, unchecked",
        "tr": "Bulutun şu anda tuttukları", "kk": "Бұлтта қазір бар нәрсе",
        "uz": "Bulutda hozir bor narsa", "az": "Bulutda indi olan",
    },
    "lens.was": {
        "ru": "Было", "en": "Was", "tr": "Önceden",
        "kk": "Болғаны", "uz": "Boʻlgani", "az": "Əvvəl",
    },
    "lens.was.title": {
        "ru": "Вся опись с судьбой каждого файла: спасён, удалён, не взят",
        "en": "The whole inventory with each file fate: saved, deleted, never taken",
        "tr": "Her dosyanın kaderiyle tüm envanter", "kk": "Әр файлдың тағдырымен бүкіл тізім",
        "uz": "Har bir fayl taqdiri bilan butun roʻyxat", "az": "Hər faylın taleyi ilə bütün siyahı",
    },
    "lens.disk": {
        "ru": "На диске", "en": "On disk", "tr": "Diskte",
        "kk": "Дискіде", "uz": "Diskda", "az": "Diskdə",
    },
    "lens.disk.title": {
        "ru": "Что спасено и лежит у тебя: целое, с дырками, пропавшее",
        "en": "What is rescued and sits on your disk",
        "tr": "Kurtarılıp diskinde duranlar", "kk": "Құтқарылып дискіде жатқан",
        "uz": "Qutqarilib diskda yotgan", "az": "Xilas edilib diskdə olan",
    },
    "act.scan": {
        "ru": "Опись", "en": "Inventory", "tr": "Envanter",
        "kk": "Тізім", "uz": "Roʻyxat", "az": "Siyahı",
    },
    "act.scan.title": {
        "ru": "Обойти облако и записать, что в нём есть",
        "en": "Walk the cloud and record what it holds",
        "tr": "Bulutu dolaşıp ne olduğunu yaz", "kk": "Бұлтты аралап, не бар екенін жазу",
        "uz": "Bulutni aylanib, nima borligini yozish", "az": "Bulutu gəzib nə olduğunu yaz",
    },
    "act.scan.left": {
        "ru": "папок в очереди", "en": "folders queued", "tr": "klasör sırada",
        "kk": "қатардағы қалта", "uz": "navbatdagi papka", "az": "növbədə qovluq",
    },
    "act.scan.done": {
        "ru": "опись закончена", "en": "inventory complete", "tr": "envanter bitti",
        "kk": "тізім бітті", "uz": "roʻyxat tugadi", "az": "siyahı bitdi",
    },
    "act.loop": {
        "ru": "Круг", "en": "Loop", "tr": "Tur",
        "kk": "Айналым", "uz": "Tur", "az": "Tur",
    },
    "act.loop.title": {
        "ru": "Брать всё, что осталось, круг за кругом, пока не остановишь",
        "en": "Take what is left, round after round, until stopped",
        "tr": "Kalanı tur tur al", "kk": "Қалғанын айналыммен алу",
        "uz": "Qolganini tur bilan olish", "az": "Qalanı tur ilə götür",
    },
    "act.loop.take": {
        "ru": "взять · {size}", "en": "to take · {size}", "tr": "alınacak · {size}",
        "kk": "алу · {size}", "uz": "olish · {size}", "az": "götürmək · {size}",
    },
    "act.loop.empty": {
        "ru": "брать нечего", "en": "nothing to take", "tr": "alınacak yok",
        "kk": "алатын ештеңе жоқ", "uz": "oladigan narsa yoq", "az": "götürüləsi yox",
    },
    "act.archive": {
        "ru": "Архив", "en": "Archive", "tr": "Arşiv",
        "kk": "Мұрағат", "uz": "Arxiv", "az": "Arxiv",
    },
    "act.archive.title": {
        "ru": "Упаковать спасённое в тома по 3.9 ГБ под Телеграм",
        "en": "Pack what is rescued into 3.9 GB volumes for Telegram",
        "tr": "Kurtarılanı 3.9 GB ciltlere paketle", "kk": "Құтқарылғанды 3.9 ГБ томдарға жинау",
        "uz": "Qutqarilganni 3.9 GB jildlarga jamlash", "az": "Xilas ediləni 3.9 GB cildlərə yığ",
    },
    "act.archive.wait": {
        "ru": "упаковать · {size}", "en": "to pack · {size}", "tr": "paketlenecek · {size}",
        "kk": "жинау · {size}", "uz": "jamlanadi · {size}", "az": "yığılacaq · {size}",
    },
    "act.archive.empty": {
        "ru": "всё упаковано", "en": "all packed", "tr": "hepsi paketlendi",
        "kk": "бәрі жиналды", "uz": "hammasi jamlandi", "az": "hamısı yığıldı",
    },
    "act.delete": {
        "ru": "Удалить из облака", "en": "Delete from cloud", "tr": "Buluttan sil",
        "kk": "Бұлттан жою", "uz": "Bulutdan oʻchirish", "az": "Bulutdan sil",
    },
    "act.delete.title": {
        "ru": "Освободить место в облаке тем, что уже спасено",
        "en": "Free cloud space with what is already rescued",
        "tr": "Kurtarılmış olanla bulutta yer aç", "kk": "Құтқарылғанмен бұлтта орын босату",
        "uz": "Qutqarilgan bilan bulutda joy boʻshatish", "az": "Xilas edilmişlə bulutda yer aç",
    },
    "act.delete.ready": {
        "ru": "готово к удалению", "en": "ready to delete", "tr": "silmeye hazır",
        "kk": "жоюға дайын", "uz": "oʻchirishga tayyor", "az": "silməyə hazır",
    },
    "act.delete.empty": {
        "ru": "в облаке ничего не осталось", "en": "nothing left in the cloud",
        "tr": "bulutta bir şey kalmadı", "kk": "бұлтта ештеңе қалмады",
        "uz": "bulutda hech narsa qolmadi", "az": "bulutda heç nə qalmadı",
    },
    "n.volumes": {
        "ru": {"one": "том", "few": "тома", "many": "томов"},
        "en": {"one": "volume", "other": "volumes"},
        "tr": {"one": "cilt", "other": "cilt"},
        "kk": {"one": "том", "other": "том"},
        "uz": {"one": "jild", "other": "jild"},
        "az": {"one": "cild", "other": "cild"},
    },
    "act.loop.takeSel": {
        "ru": "из выбранного · {size}", "en": "take from selection · {size}",
        "tr": "seçimden al · {size}", "kk": "таңдаудан алу · {size}",
        "uz": "tanlovdan olish · {size}", "az": "seçimdən götür · {size}",
    },
    "act.archive.sel": {
        "ru": "из выбранного · {n} {volumes}", "en": "pack · {n} {volumes}",
        "tr": "paketle · {n} {volumes}", "kk": "жинау · {n} {volumes}",
        "uz": "jamlash · {n} {volumes}", "az": "yığ · {n} {volumes}",
    },
    "act.delete.emptySel": {
        "ru": "в выбранном нечего удалять", "en": "nothing to delete here",
        "tr": "seçimde silinecek yok", "kk": "таңдауда жоятын ештеңе жоқ",
        "uz": "tanlovda oʻchiradigan narsa yoq", "az": "seçimdə silinəsi yox",
    },
    "act.delete.sel": {
        "ru": "в выбранном готово", "en": "ready in selection",
        "tr": "seçimde hazır", "kk": "таңдауда дайын",
        "uz": "tanlovda tayyor", "az": "seçimdə hazır",
    },
    "auth.signIn": {
        "ru": "Войти", "en": "Sign in", "tr": "Giriş yap",
        "kk": "Кіру", "uz": "Kirish", "az": "Daxil ol",
    },
    "auth.dead": {
        "ru": "Токен не принят", "en": "Token rejected", "tr": "Belirteç reddedildi",
        "kk": "Токен қабылданбады", "uz": "Token rad etildi", "az": "Token rədd edildi",
    },
    "auth.dead.why": {
        "ru": "Облако отвергло токен — войдите заново",
        "en": "The cloud rejected the token — sign in again",
        "tr": "Bulut belirteci reddetti — yeniden giriş yapın",
        "kk": "Бұлт токенді қабылдамады — қайта кіріңіз",
        "uz": "Bulut tokenni rad etdi — qaytadan kiring",
        "az": "Bulut tokeni rədd etdi — yenidən daxil olun",
    },
    "auth.tokenOnly": {
        "ru": "Токен есть", "en": "Token set", "tr": "Belirteç var",
        "kk": "Токен бар", "uz": "Token bor", "az": "Token var",
    },
    "auth.checkedAt": {
        "ru": "Проверено {when}", "en": "Checked {when}", "tr": "Denetlendi {when}",
        "kk": "Тексерілді {when}", "uz": "Tekshirildi {when}", "az": "Yoxlanıldı {when}",
    },
    "auth.space": {
        "ru": "Занято {used} из {total}", "en": "{used} of {total} used",
        "tr": "{total} içinden {used} dolu", "kk": "{total} ішінен {used} бос емес",
        "uz": "{total} ichidan {used} band", "az": "{total} içindən {used} dolu",
    },
    "auth.clickToManage": {
        "ru": "Нажмите, чтобы сменить аккаунт или токен",
        "en": "Click to change the account or token",
        "tr": "Hesabı veya belirteci değiştirmek için tıklayın",
        "kk": "Аккаунтты немесе токенді ауыстыру үшін басыңыз",
        "uz": "Akkaunt yoki tokenni almashtirish uchun bosing",
        "az": "Hesabı və ya tokeni dəyişmək üçün basın",
    },
    "auth.noAccount": {
        "ru": "Сведений об аккаунте нет", "en": "No account details yet",
        "tr": "Hesap bilgisi yok", "kk": "Аккаунт туралы мәлімет жоқ",
        "uz": "Akkaunt haqida maʼlumot yoq", "az": "Hesab məlumatı yoxdur",
    },
    "auth.refreshInfo": {
        "ru": "Обновить", "en": "Refresh", "tr": "Yenile",
        "kk": "Жаңарту", "uz": "Yangilash", "az": "Yenilə",
    },
    "tools.title": {
        "ru": "Инструменты", "en": "Tools", "tr": "Araçlar",
        "kk": "Құралдар", "uz": "Asboblar", "az": "Alətlər",
    },
    "tools.hint": {
        "ru": "Вспомогательные действия. Главное — четыре кнопки сверху.",
        "en": "Secondary actions. The four buttons above are the main ones.",
        "tr": "Yardımcı eylemler. Asıl iş yukarıdaki dört düğmede.",
        "kk": "Көмекші әрекеттер. Негізгісі — жоғарыдағы төрт түйме.",
        "uz": "Yordamchi amallar. Asosiysi — yuqoridagi toʻrtta tugma.",
        "az": "Köməkçi əməliyyatlar. Əsası — yuxarıdaki dörd düymə.",
    },
    "tools.previews.why": {
        "ru": "Добрать картинки для превью", "en": "Fetch missing preview images",
        "tr": "Eksik önizleme görsellerini al", "kk": "Превью суреттерін жинау",
        "uz": "Koʻrish rasmlarini yigʻish", "az": "Önizləmə şəkillərini yığ",
    },
    "tools.restart.why": {
        "ru": "Начать опись с нуля, не продолжая с места обрыва",
        "en": "Start the inventory from scratch instead of resuming",
        "tr": "Envanteri kaldığı yerden değil, sıfırdan başlat",
        "kk": "Тізімді үзілген жерден емес, нөлден бастау",
        "uz": "Roʻyxatni toʻxtagan joydan emas, noldan boshlash",
        "az": "Siyahını kəsildiyi yerdən deyil, sıfırdan başlat",
    },
    "tools.probe.why": {
        "ru": "Спросить у хранилища, что ещё отдаётся",
        "en": "Ask the storage what is still served",
        "tr": "Depoya nelerin hâlâ verildiğini sor",
        "kk": "Қоймадан әлі не берілетінін сұрау",
        "uz": "Ombordan hali nima berilishini soʻrash",
        "az": "Anbardan hələ nə verildiyini soruş",
    },
    "tools.autopilot.why": {
        "ru": "Раз в несколько часов перепроверять недоступное",
        "en": "Re-check unavailable files every few hours",
        "tr": "Erişilemeyenleri birkaç saatte bir yeniden dene",
        "kk": "Қолжетімсіздерді бірнеше сағат сайын қайта тексеру",
        "uz": "Ishlamaydiganlarni bir necha soatda qayta tekshirish",
        "az": "Əlçatmazları bir neçə saatdan bir yenidən yoxla",
    },
    "tools.hosts.why": {
        "ru": "Узлы и кластеры: где висит остаток",
        "en": "Nodes and clusters: where the remainder sits",
        "tr": "Düğümler ve kümeler: kalan nerede",
        "kk": "Түйіндер мен кластерлер: қалдық қайда",
        "uz": "Tugunlar va klasterlar: qoldiq qayerda",
        "az": "Qovşaqlar və klasterlər: qalıq harada",
    },
    "tools.download.why": {
        "ru": "Скачать только отмеченное в дереве",
        "en": "Download only what is ticked in the tree",
        "tr": "Yalnız ağaçta işaretlenenleri indir",
        "kk": "Тек ағашта белгіленгенді жүктеу",
        "uz": "Faqat daraxtda belgilanganini yuklash",
        "az": "Yalnız ağacda işarələnəni endir",
    },
    "salvage.short": {
        "ru": "Спасать с дырками", "en": "Keep holed files", "tr": "Delikli sakla",
        "kk": "Тесікті сақтау", "uz": "Teshikli saqlash", "az": "Deşikli saxla",
    },
    "tools.salvage.why": {
        "ru": "Спасать файл с дырками, если он обрывается",
        "en": "Keep a holed file when the transfer breaks",
        "tr": "Aktarım koparsa delikli dosyayı sakla",
        "kk": "Тасымал үзілсе, тесікті файлды сақтау",
        "uz": "Uzatish uzilsa, teshikli faylni saqlash",
        "az": "Köçürmə qırılarsa, deşikli faylı saxla",
    },
    "tools.archives.why": {
        "ru": "Список томов, проверка, освобождение оригиналов",
        "en": "Volumes, verification, freeing originals",
        "tr": "Ciltler, doğrulama, orijinalleri boşaltma",
        "kk": "Томдар, тексеру, түпнұсқаларды босату",
        "uz": "Jildlar, tekshiruv, asl nusxalarni boʻshatish",
        "az": "Cildlər, yoxlama, orijinalları azad etmə",
    },
    "tools.adopt.why": {
        "ru": "Учесть файлы, спасённые вручную",
        "en": "Register files you rescued by hand",
        "tr": "Elle kurtardığınız dosyaları hesaba kat",
        "kk": "Қолмен құтқарылған файлдарды есепке алу",
        "uz": "Qoʻlda qutqarilgan fayllarni hisobga olish",
        "az": "Əllə xilas etdiklərinizi hesaba al",
    },
    "tools.mirror.why": {
        "ru": "Сверить зеркало с диском прямо сейчас",
        "en": "Sync the mirror with the disk right now",
        "tr": "Aynayı diskle hemen eşitle",
        "kk": "Айнаны дискімен қазір салыстыру",
        "uz": "Oynani disk bilan hozir solishtirish",
        "az": "Aynanı disklə indi tutuşdur",
    },
    "tools.health.why": {
        "ru": "Почему не выходит: причины, узлы, задачи",
        "en": "Why it fails: reasons, nodes, jobs",
        "tr": "Neden olmuyor: nedenler, düğümler, görevler",
        "kk": "Неге шықпайды: себептер, түйіндер, тапсырмалар",
        "uz": "Nega chiqmaydi: sabablar, tugunlar, vazifalar",
        "az": "Niyə alınmır: səbəblər, qovşaqlar, tapşırıqlar",
    },
    "tools.log.why": {
        "ru": "Последние строки журнала", "en": "The latest log lines",
        "tr": "Günlüğün son satırları", "kk": "Журналдың соңғы жолдары",
        "uz": "Jurnalning oxirgi satrlari", "az": "Jurnalın son sətirləri",
    },
    "tools.settings.why": {
        "ru": "Куда спасать", "en": "Where to save", "tr": "Nereye kaydedilecek",
        "kk": "Қайда сақтау", "uz": "Qayerga saqlash", "az": "Harada saxlamaq",
    },
    "btn.probe.run": {
        "ru": "Проверить", "en": "Run", "tr": "Çalıştır",
        "kk": "Тексеру", "uz": "Tekshirish", "az": "Yoxla",
    },
    "arch.volume": {
        "ru": "Размер тома", "en": "Volume size", "tr": "Cilt boyutu",
        "kk": "Том өлшемі", "uz": "Jild oʻlchami", "az": "Cild ölçüsü",
    },
    "arch.compression": {
        "ru": "Сжатие", "en": "Compression", "tr": "Sıkıştırma",
        "kk": "Сығу", "uz": "Siqish", "az": "Sıxılma",
    },
    "arch.vol.3900": {
        "ru": "3900 МБ — премиум Телеграм", "en": "3900 MB — Telegram Premium",
        "tr": "3900 MB — Telegram Premium", "kk": "3900 МБ — Telegram Premium",
        "uz": "3900 MB — Telegram Premium", "az": "3900 MB — Telegram Premium",
    },
    "arch.vol.1900": {
        "ru": "1900 МБ — обычный Телеграм", "en": "1900 MB — regular Telegram",
        "tr": "1900 MB — normal Telegram", "kk": "1900 МБ — қарапайым Telegram",
        "uz": "1900 MB — oddiy Telegram", "az": "1900 MB — adi Telegram",
    },
    "arch.vol.none": {
        "ru": "Не дробить", "en": "Do not split", "tr": "Bölme",
        "kk": "Бөлмеу", "uz": "Boʻlmaslik", "az": "Bölmə",
    },
    "arch.vol.none.short": {
        "ru": "одним файлом", "en": "single file", "tr": "tek dosya",
        "kk": "бір файл", "uz": "bitta fayl", "az": "bir fayl",
    },
    "arch.comp.store": {
        "ru": "Без сжатия (быстро)", "en": "Store (fast)", "tr": "Sıkıştırmasız (hızlı)",
        "kk": "Сығусыз (жылдам)", "uz": "Siqishsiz (tez)", "az": "Sıxılmadan (sürətli)",
    },
    "arch.comp.normal": {
        "ru": "Обычное", "en": "Normal", "tr": "Normal",
        "kk": "Қалыпты", "uz": "Oddiy", "az": "Adi",
    },
    "arch.comp.max": {
        "ru": "Максимальное (медленно)", "en": "Maximum (slow)", "tr": "Maksimum (yavaş)",
        "kk": "Ең жоғары (баяу)", "uz": "Maksimal (sekin)", "az": "Maksimal (yavaş)",
    },
    "arch.list": {
        "ru": "Архивы…", "en": "Archives…", "tr": "Arşivler…",
        "kk": "Мұрағаттар…", "uz": "Arxivlar…", "az": "Arxivlər…",
    },
    "view.title": {
        "ru": "Вид", "en": "View", "tr": "Görünüm",
        "kk": "Көрініс", "uz": "Koʻrinish", "az": "Görünüş",
    },
    "view.scale": {
        "ru": "Масштаб", "en": "Scale", "tr": "Ölçek",
        "kk": "Масштаб", "uz": "Masshtab", "az": "Miqyas",
    },
    "view.density": {
        "ru": "Плотность", "en": "Density", "tr": "Yoğunluk",
        "kk": "Тығыздық", "uz": "Zichlik", "az": "Sıxlıq",
    },
    "view.density.normal": {
        "ru": "Обычная", "en": "Normal", "tr": "Normal",
        "kk": "Қалыпты", "uz": "Oddiy", "az": "Adi",
    },
    "view.density.compact": {
        "ru": "Компактная", "en": "Compact", "tr": "Kompakt",
        "kk": "Ықшам", "uz": "Ixcham", "az": "Kompakt",
    },
    "view.autoShort": {
        "ru": "авто", "en": "auto", "tr": "oto",
        "kk": "авто", "uz": "avto", "az": "avto",
    },
    "view.auto": {
        "ru": "Подстроено под экран: {pct}%",
        "en": "Fitted to the screen: {pct}%",
        "tr": "Ekrana uyarlandı: {pct}%",
        "kk": "Экранға бейімделді: {pct}%",
        "uz": "Ekrannga moslashtirildi: {pct}%",
        "az": "Ekrana uyğunlaşdırıldı: {pct}%",
    },
    "view.manual": {
        "ru": "Свой масштаб: {pct}%", "en": "Custom scale: {pct}%",
        "tr": "Özel ölçek: {pct}%", "kk": "Өз масштабыңыз: {pct}%",
        "uz": "Oʻz masshtabingiz: {pct}%", "az": "Öz miqyasınız: {pct}%",
    },
    "theme.title": {
        "ru": "Тема", "en": "Theme", "tr": "Tema",
        "kk": "Тақырып", "uz": "Mavzu", "az": "Mövzu",
    },
    "theme.auto": {
        "ru": "как в системе", "en": "follow system", "tr": "sistem gibi",
        "kk": "жүйедегідей", "uz": "tizimdagidek", "az": "sistemdəki kimi",
    },
    "theme.light": {
        "ru": "светлая", "en": "light", "tr": "açık",
        "kk": "ашық", "uz": "yorugʻ", "az": "işıqlı",
    },
    "theme.dark": {
        "ru": "тёмная", "en": "dark", "tr": "koyu",
        "kk": "қараңғы", "uz": "qorongʻi", "az": "tünd",
    },
    "setup.title": {
        "ru": "Начало работы", "en": "Getting started", "tr": "Başlangıç",
        "kk": "Жұмысты бастау", "uz": "Ishni boshlash", "az": "İşə başlama",
    },
    "setup.hide": {
        "ru": "Скрыть чеклист", "en": "Hide the checklist", "tr": "Listeyi gizle",
        "kk": "Тізімді жасыру", "uz": "Roʻyxatni yashirish", "az": "Siyahını gizlət",
    },
    "setup.token": {
        "ru": "Токен доступа", "en": "Access token", "tr": "Erişim belirteci",
        "kk": "Қатынас токені", "uz": "Kirish tokeni", "az": "Giriş tokeni",
    },
    "setup.token.why": {
        "ru": "Без него облако не отвечает", "en": "Without it the cloud does not answer",
        "tr": "Onsuz bulut yanıt vermez", "kk": "Онсыз бұлт жауап бермейді",
        "uz": "Usiz bulut javob bermaydi", "az": "Onsuz bulut cavab vermir",
    },
    "setup.scan": {
        "ru": "Опись диска", "en": "Inventory the disk", "tr": "Diski listele",
        "kk": "Дискіні тізімдеу", "uz": "Diskni roʻyxatga olish", "az": "Diski siyahıya al",
    },
    "setup.scan.why": {
        "ru": "Программа узнает, что вообще было в облаке",
        "en": "The program learns what the cloud held",
        "tr": "Program bulutta ne olduğunu öğrenir",
        "kk": "Бағдарлама бұлтта не болғанын біледі",
        "uz": "Dastur bulutda nima boʻlganini biladi",
        "az": "Proqram bulutda nə olduğunu öyrənir",
    },
    "setup.rescue": {
        "ru": "Первое спасение", "en": "First rescue", "tr": "İlk kurtarma",
        "kk": "Алғашқы құтқару", "uz": "Birinchi qutqarish", "az": "İlk xilas",
    },
    "setup.rescue.why": {
        "ru": "Круг забирает всё, что ещё можно скачать",
        "en": "The loop takes everything still downloadable",
        "tr": "Tur indirilebilen her şeyi alır",
        "kk": "Айналым жүктеуге болатынның бәрін алады",
        "uz": "Tur yuklash mumkin boʻlgan hammasini oladi",
        "az": "Tur endirilə bilən hər şeyi götürür",
    },
    "palette.title": {
        "ru": "Командная палитра (Ctrl+K)", "en": "Command palette (Ctrl+K)",
        "tr": "Komut paleti (Ctrl+K)", "kk": "Командалық палитра (Ctrl+K)",
        "uz": "Buyruq palitrasi (Ctrl+K)", "az": "Əmr palitrası (Ctrl+K)",
    },
    "palette.ph": {
        "ru": "Действие или папка…", "en": "Action or folder…",
        "tr": "Eylem veya klasör…", "kk": "Әрекет немесе қалта…",
        "uz": "Amal yoki papka…", "az": "Əməliyyat və ya qovluq…",
    },
    "palette.empty": {
        "ru": "Ничего не нашлось", "en": "Nothing found", "tr": "Bir şey bulunamadı",
        "kk": "Ештеңе табылмады", "uz": "Hech narsa topilmadi", "az": "Heç nə tapılmadı",
    },
    "palette.hint": {
        "ru": "↑↓ выбрать · Enter выполнить · Esc закрыть",
        "en": "↑↓ to choose · Enter to run · Esc to close",
        "tr": "↑↓ seç · Enter çalıştır · Esc kapat",
        "kk": "↑↓ таңдау · Enter орындау · Esc жабу",
        "uz": "↑↓ tanlash · Enter bajarish · Esc yopish",
        "az": "↑↓ seç · Enter icra et · Esc bağla",
    },
    "palette.ofSel": {
        "ru": "по выбору: {n}", "en": "by selection: {n}",
        "tr": "seçime göre: {n}", "kk": "таңдау бойынша: {n}",
        "uz": "tanlov boʻyicha: {n}", "az": "seçimə görə: {n}",
    },
    "cmd.on": {
        "ru": "включено", "en": "on", "tr": "açık",
        "kk": "қосулы", "uz": "yoqilgan", "az": "aktiv",
    },
    "cmd.off": {
        "ru": "выключено", "en": "off", "tr": "kapalı",
        "kk": "өшірулі", "uz": "oʻchirilgan", "az": "söndürülüb",
    },
    "cmd.lens": {
        "ru": "Линза", "en": "Lens", "tr": "Mercek",
        "kk": "Линза", "uz": "Linza", "az": "Linza",
    },
    "health.title": {
        "ru": "Здоровье", "en": "Health", "tr": "Sağlık",
        "kk": "Денсаулық", "uz": "Salomatlik", "az": "Sağlamlıq",
    },
    "health.saved24": {
        "ru": "спасено за сутки", "en": "rescued in 24 h",
        "tr": "24 saatte kurtarılan", "kk": "тәулікте құтқарылды",
        "uz": "sutkada qutqarildi", "az": "sutkada xilas edildi",
    },
    "health.deleted24": {
        "ru": "удалено из облака", "en": "deleted from cloud",
        "tr": "buluttan silinen", "kk": "бұлттан жойылды",
        "uz": "bulutdan oʻchirildi", "az": "bulutdan silindi",
    },
    "health.probes24": {
        "ru": "проб за сутки", "en": "probes in 24 h",
        "tr": "24 saatte denetim", "kk": "тәулікте тексеру",
        "uz": "sutkada tekshiruv", "az": "sutkada yoxlama",
    },
    "health.failed24": {
        "ru": "из них неудачных", "en": "of them failed",
        "tr": "bunlardan başarısız", "kk": "соның ішінде сәтсіз",
        "uz": "shundan muvaffaqiyatsiz", "az": "onlardan uğursuz",
    },
    "health.days": {
        "ru": "По дням", "en": "By day", "tr": "Güne göre",
        "kk": "Күндер бойынша", "uz": "Kunlar boʻyicha", "az": "Günlər üzrə",
    },
    "health.saved": {
        "ru": "спасено", "en": "rescued", "tr": "kurtarılan",
        "kk": "құтқарылды", "uz": "qutqarildi", "az": "xilas edildi",
    },
    "health.deleted": {
        "ru": "удалено", "en": "deleted", "tr": "silinen",
        "kk": "жойылды", "uz": "oʻchirildi", "az": "silindi",
    },
    "health.probes": {
        "ru": "проб", "en": "probes", "tr": "denetim",
        "kk": "тексеру", "uz": "tekshiruv", "az": "yoxlama",
    },
    "health.reasons": {
        "ru": "Почему не выходит", "en": "Why it fails", "tr": "Neden olmuyor",
        "kk": "Неге шықпайды", "uz": "Nega chiqmaydi", "az": "Niyə alınmır",
    },
    "health.hosts": {
        "ru": "Узлы с отказами", "en": "Nodes with failures",
        "tr": "Hata veren düğümler", "kk": "Ақаулы түйіндер",
        "uz": "Xatoli tugunlar", "az": "Xatalı qovşaqlar",
    },
    "health.gone": {
        "ru": "Почему файлов нет в облаке", "en": "Why files are not in the cloud",
        "tr": "Dosyalar neden bulutta yok", "kk": "Файлдар бұлтта неге жоқ",
        "uz": "Fayllar bulutda nega yoq", "az": "Fayllar bulutda niyə yoxdur",
    },
    "health.jobs": {
        "ru": "Задачи за неделю", "en": "Jobs for the week",
        "tr": "Haftanın görevleri", "kk": "Аптадағы тапсырмалар",
        "uz": "Haftadagi vazifalar", "az": "Həftənin tapşırıqları",
    },
    "health.jobsLine": {
        "ru": "Всего {total}, упало {failed}", "en": "{total} total, {failed} failed",
        "tr": "Toplam {total}, {failed} başarısız", "kk": "Барлығы {total}, {failed} сәтсіз",
        "uz": "Jami {total}, {failed} muvaffaqiyatsiz", "az": "Cəmi {total}, {failed} uğursuz",
    },
    "health.noFailures": {
        "ru": "Отказов нет", "en": "No failures", "tr": "Hata yok",
        "kk": "Ақау жоқ", "uz": "Xato yoq", "az": "Xəta yoxdur",
    },
    "health.source": {
        "ru": "Считается по базе: пробы, история, спасения, удаления, задачи. Лог нужен только для подробностей.",
        "en": "Computed from the database: probes, history, rescues, deletions, jobs. The log is only for details.",
        "tr": "Veritabanından hesaplanır: denetimler, geçmiş, kurtarmalar, silmeler, görevler. Günlük yalnız ayrıntı içindir.",
        "kk": "База бойынша есептеледі: байқаулар, тарих, құтқарулар, жоюлар, тапсырмалар. Лог тек мәлімет үшін.",
        "uz": "Baza boʻyicha hisoblanadi: tekshiruvlar, tarix, qutqarishlar, oʻchirishlar, vazifalar. Log faqat tafsilot uchun.",
        "az": "Baza üzrə hesablanır: yoxlamalar, tarixçə, xilaslar, silmələr, tapşırıqlar. Log yalnız təfərrüat üçündür.",
    },
    "reason.ours": {
        "ru": "удалено нами из облака", "en": "deleted from cloud by us",
        "tr": "bizim buluttan sildiğimiz", "kk": "біз бұлттан жойған",
        "uz": "biz bulutdan oʻchirgan", "az": "biz bulutdan silmişik",
    },
    "reason.no_link": {
        "ru": "облако не дало ссылку", "en": "cloud gave no link",
        "tr": "bulut bağlantı vermedi", "kk": "бұлт сілтеме бермеді",
        "uz": "bulut havola bermadi", "az": "bulut link vermədi",
    },
    "reason.not_found": {
        "ru": "файла нет (404)", "en": "file not found (404)",
        "tr": "dosya yok (404)", "kk": "файл жоқ (404)",
        "uz": "fayl yoq (404)", "az": "fayl yoxdur (404)",
    },
    "reason.silent": {
        "ru": "узел принимает и молчит", "en": "node accepts and goes silent",
        "tr": "düğüm bağlanıp susuyor", "kk": "түйін қабылдап, үнсіз қалады",
        "uz": "tugun qabul qilib jim qoladi", "az": "qovşaq qəbul edib susur",
    },
    "reason.refused": {
        "ru": "узел не принимает соединения", "en": "node refuses connections",
        "tr": "düğüm bağlantı kabul etmiyor", "kk": "түйін қосылымды қабылдамайды",
        "uz": "tugun ulanishni qabul qilmaydi", "az": "qovşaq bağlantı qəbul etmir",
    },
    "reason.dns": {
        "ru": "имя узла не разрешается", "en": "node name does not resolve",
        "tr": "düğüm adı çözülmüyor", "kk": "түйін аты шешілмейді",
        "uz": "tugun nomi hal boʻlmaydi", "az": "qovşaq adı həll olunmur",
    },
    "reason.broken": {
        "ru": "соединение рвётся на середине", "en": "connection drops mid-transfer",
        "tr": "bağlantı ortada kopuyor", "kk": "қосылым ортасында үзіледі",
        "uz": "ulanish oʻrtada uziladi", "az": "bağlantı ortada qırılır",
    },
    "reason.truncated": {
        "ru": "файл обрезан на машине", "en": "file is truncated on the machine",
        "tr": "dosya makinede kesilmiş", "kk": "файл машинада қиылған",
        "uz": "fayl mashinada qirqilgan", "az": "fayl maşında kəsilmiş",
    },
    "reason.no_copy": {
        "ru": "облако не нашло копию", "en": "cloud found no copy",
        "tr": "bulut kopya bulamadı", "kk": "бұлт көшірме таппады",
        "uz": "bulut nusxa topmadi", "az": "bulut kopya tapmadı",
    },
    "reason.ok": {
        "ru": "отдаётся", "en": "served", "tr": "veriliyor",
        "kk": "беріледі", "uz": "beriladi", "az": "verilir",
    },
    "reason.misc": {
        "ru": "прочее", "en": "other", "tr": "diğer",
        "kk": "басқа", "uz": "boshqa", "az": "digər",
    },
    "help.title": {
        "ru": "Клавиши", "en": "Keyboard", "tr": "Klavye",
        "kk": "Пернелер", "uz": "Klaviatura", "az": "Klaviatura",
    },
    "help.search": {
        "ru": "поиск по имени файла", "en": "search by file name",
        "tr": "dosya adına göre arama", "kk": "файл аты бойынша іздеу",
        "uz": "fayl nomi boʻyicha qidiruv", "az": "fayl adı ilə axtarış",
    },
    "help.move": {
        "ru": "ходить по дереву", "en": "move through the tree",
        "tr": "ağaçta gezinme", "kk": "ағаш бойынша жүру",
        "uz": "daraxt boʻylab yurish", "az": "ağac üzrə hərəkət",
    },
    "help.select": {
        "ru": "отметить строку", "en": "select the row",
        "tr": "satırı işaretle", "kk": "жолды белгілеу",
        "uz": "qatorni belgilash", "az": "sətri işarələ",
    },
    "help.open": {
        "ru": "раскрыть папку / подробности файла",
        "en": "expand folder / file details",
        "tr": "klasörü aç / dosya ayrıntıları",
        "kk": "қалтаны ашу / файл мәліметтері",
        "uz": "papkani ochish / fayl tafsilotlari",
        "az": "qovluğu aç / fayl təfərrüatları",
    },
    "help.fold": {
        "ru": "свернуть и развернуть папку", "en": "collapse and expand a folder",
        "tr": "klasörü kapat ve aç", "kk": "қалтаны жабу және ашу",
        "uz": "papkani yopish va ochish", "az": "qovluğu yığ və aç",
    },
    "help.esc": {
        "ru": "закрыть окно, снять поиск", "en": "close dialog, clear search",
        "tr": "pencereyi kapat, aramayı temizle", "kk": "терезені жабу, іздеуді тазалау",
        "uz": "oynani yopish, qidiruvni tozalash", "az": "pəncərəni bağla, axtarışı təmizlə",
    },
    "help.help": {
        "ru": "эта справка", "en": "this help", "tr": "bu yardım",
        "kk": "осы анықтама", "uz": "bu yordam", "az": "bu yardım",
    },
    "jobs.okTitle": {
        "ru": "прошли без ошибок", "en": "finished without errors",
        "tr": "hatasız bitti", "kk": "қатесіз аяқталды",
        "uz": "xatosiz tugadi", "az": "xətasız bitdi",
    },
    "jobs.badTitle": {
        "ru": "завершились с ошибками или отменены",
        "en": "failed or cancelled", "tr": "hatalı veya iptal",
        "kk": "қатемен немесе тоқтатылды", "uz": "xato yoki bekor",
        "az": "xəta və ya ləğv",
    },
    "jobs.expand": {
        "ru": "показать", "en": "show", "tr": "göster",
        "kk": "көрсету", "uz": "koʻrsatish", "az": "göstər",
    },
    "jobs.collapse": {
        "ru": "свернуть", "en": "collapse", "tr": "daralt",
        "kk": "жию", "uz": "yigʻish", "az": "yığ",
    },
    "jobs.recentN": {
        "ru": "завершено {n} {jobs}", "en": "{n} {jobs} finished",
        "tr": "{n} {jobs} bitti", "kk": "{n} {jobs} аяқталды",
        "uz": "{n} {jobs} tugadi", "az": "{n} {jobs} bitdi",
    },
    "n.jobs": {
        "ru": {"one": "задача", "few": "задачи", "many": "задач"},
        "en": {"one": "job", "other": "jobs"},
        "tr": {"one": "görev", "other": "görev"},
        "kk": {"one": "тапсырма", "other": "тапсырма"},
        "uz": {"one": "vazifa", "other": "vazifa"},
        "az": {"one": "tapşırıq", "other": "tapşırıq"},
    },
    "tile.free": {
        "ru": "свободно на {drive} {size}", "en": "free on {drive} {size}",
        "tr": "{drive} boş {size}", "kk": "{drive} бос {size}",
        "uz": "{drive} boʻsh {size}", "az": "{drive} boş {size}",
    },
    "tile.verifiedOf": {
        "ru": "проверено {n} {files}", "en": "verified {n} {files}",
        "tr": "doğrulandı {n} {files}", "kk": "тексерілді {n} {files}",
        "uz": "tekshirildi {n} {files}", "az": "yoxlanıldı {n} {files}",
    },
    "tile.staleLine": {
        "ru": "устарело {n} {files} · старейшее наблюдение {when}",
        "en": "stale {n} {files} · oldest observation {when}",
        "tr": "eskimiş {n} {files} · en eski gözlem {when}",
        "kk": "ескірген {n} {files} · ең ескі байқау {when}",
        "uz": "eskirgan {n} {files} · eng eski kuzatuv {when}",
        "az": "köhnəlmiş {n} {files} · ən köhnə müşahidə {when}",
    },
    "tile.stale.title": {
        "ru": "Наблюдение старше срока годности ({hours} ч): «доступно» — это воспоминание, а не факт",
        "en": "The observation is past its shelf life ({hours} h): “available” is a memory, not a fact",
        "tr": "Gözlem raf ömrünü geçmiş ({hours} sa): “erişilebilir” bir anı, gerçek değil",
        "kk": "Байқау мерзімі өткен ({hours} сағ): «қолжетімді» — естелік, факт емес",
        "uz": "Kuzatuv muddati oʻtgan ({hours} soat): «ishlaydi» — xotira, fakt emas",
        "az": "Müşahidə müddəti keçib ({hours} saat): “əlçatandır” — xatirə, fakt deyil",
    },
    "sel.hint": {
        "ru": "Отметьте папку или файл — кнопки посчитают по выбору",
        "en": "Tick a folder or file — the buttons will count by your selection",
        "tr": "Bir klasör veya dosya işaretleyin — düğmeler seçime göre sayar",
        "kk": "Қалтаны немесе файлды белгілеңіз — түймелер таңдау бойынша санайды",
        "uz": "Papka yoki faylni belgilang — tugmalar tanlov boʻyicha hisoblaydi",
        "az": "Qovluq və ya fayl işarələyin — düymələr seçimə görə sayacaq",
    },
    "jobs.hide": {
        "ru": "скрыть", "en": "hide", "tr": "gizle",
        "kk": "жасыру", "uz": "yashirish", "az": "gizlət",
    },
    "jobs.id": {
        "ru": "задача #{id}", "en": "job #{id}", "tr": "görev #{id}",
        "kk": "#{id} тапсырма", "uz": "#{id} vazifa", "az": "#{id} tapşırıq",
    },
    "more.title": {
        "ru": "Ещё", "en": "More", "tr": "Daha", "kk": "Тағы", "uz": "Yana", "az": "Daha",
    },
    "grp.archive": {
        "ru": "Архив", "en": "Archive", "tr": "Arşiv", "kk": "Мұрағат",
        "uz": "Arxiv", "az": "Arxiv",
    },
    "grp.service": {
        "ru": "Сервис", "en": "Service", "tr": "Servis", "kk": "Сервис",
        "uz": "Servis", "az": "Servis",
    },
    "summary.now": {
        "ru": "{files} в облаке", "en": "{files} in the cloud",
        "tr": "bulutta {files}", "kk": "бұлтта {files}",
        "uz": "bulutda {files}", "az": "bulutda {files}",
    },
    "summary.was": {
        "ru": "{n} {files} · {size} было в описи", "en": "{n} {files} · {size} in the inventory",
        "tr": "envanterde {n} {files} · {size}", "kk": "тізімде {n} {files} · {size}",
        "uz": "roʻyxatda {n} {files} · {size}", "az": "siyahıda {n} {files} · {size}",
    },
    "summary.disk": {
        "ru": "{n} {files} · {size} на диске", "en": "{n} {files} · {size} on disk",
        "tr": "diskte {n} {files} · {size}", "kk": "дискіде {n} {files} · {size}",
        "uz": "diskda {n} {files} · {size}", "az": "diskdə {n} {files} · {size}",
    },
    "summary.savedShort": {
        "ru": "спасено {n} {files}", "en": "rescued {n} {files}",
        "tr": "kurtarıldı {n} {files}", "kk": "құтқарылды {n} {files}",
        "uz": "qutqarildi {n} {files}", "az": "xilas edildi {n} {files}",
    },
    "badge.vanishedN": {
        "ru": "удалено тобой {n}", "en": "you deleted {n}",
        "tr": "sen sildin {n}", "kk": "өзің жойдың {n}",
        "uz": "oʻzing oʻchirding {n}", "az": "özün sildin {n}",
    },
    "tree.showEmpty": {
        "ru": "показать пустые", "en": "show empty", "tr": "boşları göster",
        "kk": "бос қалталарды көрсету", "uz": "boʻshlarni koʻrsatish", "az": "boşları göstər",
    },
    "tree.showEmpty.title": {
        "ru": "Папки, от которых в облаке ничего не осталось, скрыты — эта кнопка их показывает",
        "en": "Folders with nothing left in the cloud are hidden; this shows them",
        "tr": "Bulutta bir şey kalmayan klasörler gizli",
        "kk": "Бұлтта ештеңе қалмаған қалталар жасырылған",
        "uz": "Bulutda hech narsa qolmagan papkalar yashirilgan",
        "az": "Bulutda heç nə qalmayan qovluqlar gizlədilib",
    },
    "del.choose": {
        "ru": "Что удалять из облака", "en": "What to delete from the cloud",
        "tr": "Buluttan ne silinsin", "kk": "Бұлттан нені жою керек",
        "uz": "Bulutdan nima oʻchirilsin", "az": "Bulutdan nə silinsin",
    },
    "del.chooseWhy": {
        "ru": "Три разных решения. В любом случае сначала покажу, сколько файлов попадёт под удаление и почему остальные заблокированы.",
        "en": "Three different decisions. In every case I first show how many files would go and why the rest are blocked.",
        "tr": "Üç farklı karar. Her durumda önce kaç dosyanın gideceğini gösteririm.",
        "kk": "Үш түрлі шешім. Алдымен қанша файл кететінін көрсетемін.",
        "uz": "Uch xil qaror. Avval qancha fayl ketishini koʻrsataman.",
        "az": "Üç fərqli qərar. Əvvəlcə nə qədər fayl gedəcəyini göstərəcəm.",
    },
    "del.level.downloaded.why": {
        "ru": "копия есть и хеш сошёлся — облако больше не нужно",
        "en": "a copy exists and the hash matches — the cloud copy is not needed",
        "tr": "kopya var ve hash tutuyor", "kk": "көшірме бар және хеш сәйкес",
        "uz": "nusxa bor va xesh mos", "az": "kopya var və heş uyğundur",
    },
    "del.level.archived.why": {
        "ru": "упаковано в тома и проверено — место в облаке освобождается",
        "en": "packed into volumes and verified — the cloud space is freed",
        "tr": "ciltlere paketlendi ve doğrulandı", "kk": "томдарға жиналып тексерілді",
        "uz": "jildlarga jamlanib tekshirildi", "az": "cildlərə yığılıb yoxlanıldı",
    },
    "del.level.junk.why": {
        "ru": "мусор по имени файла — удаляется даже без копии",
        "en": "junk by file name — deleted even without a copy",
        "tr": "dosya adına göre çöp", "kk": "файл аты бойынша қоқыс",
        "uz": "fayl nomi boʻyicha axlat", "az": "fayl adına görə zibil",
    },
    "hosts.open": {
        "ru": "открыть узлы и кластеры", "en": "open nodes and clusters",
        "tr": "düğümleri aç", "kk": "түйіндерді ашу",
        "uz": "tugunlarni ochish", "az": "qovşaqları aç",
    },
    "hosts.title": {
        "ru": "Узлы и кластеры", "en": "Nodes and clusters",
        "tr": "Düğümler ve kümeler", "kk": "Түйіндер мен кластерлер",
        "uz": "Tugunlar va klasterlar", "az": "Qovşaqlar və klasterlər",
    },
    "hosts.how": {
        "ru": "Узел при выгрузке выбрать нельзя: ссылку выдаёт API Яндекса и сам выбирает машину. Но повторный запрос иногда отдаёт другую — «попробовать» просит ссылки заново для файлов этого узла или кластера. Кластер — это ЦОД: klg принимает соединение и замолкает, vla не принимает вовсе.",
        "en": "You cannot pick a node when downloading: the Yandex API issues the link and chooses the machine. But a repeated request sometimes returns a different one, so \"try\" asks for links again for this node or cluster. A cluster is a data centre: klg accepts a connection and goes silent, vla does not accept at all.",
        "tr": "İndirirken düğüm seçilemez: bağlantıyı Yandex API'si verir ve makineyi kendi seçer. Ama tekrarlanan istek bazen başka birini döndürür, bu yüzden \"dene\" bu düğüm veya küme için bağlantıları yeniden ister. Küme bir veri merkezidir: klg bağlantıyı kabul edip susar, vla hiç kabul etmez.",
        "kk": "Жүктеу кезінде түйінді таңдау мүмкін емес: сілтемені Яндекс API береді және машинаны өзі таңдайды. Бірақ қайталап сұрау кейде басқа машинаны қайтарады, сондықтан \"байқау\" осы түйін немесе кластер үшін сілтемелерді қайта сұрайды. Кластер — бұл ЦОД: klg қосылымды қабылдап, үнсіз қалады, vla мүлде қабылдамайды.",
        "uz": "Yuklashda tugunni tanlash mumkin emas: havolani Yandex API beradi va mashinani oʻzi tanlaydi. Lekin takroriy soʻrov baʼzan boshqasini qaytaradi, shuning uchun \"sinash\" bu tugun yoki klaster uchun havolalarni qaytadan soʻraydi. Klaster — bu maʼlumot markazi: klg ulanishni qabul qilib jim qoladi, vla umuman qabul qilmaydi.",
        "az": "Endirmə zamanı qovşaq seçmək olmur: linki Yandex API verir və maşını özü seçir. Lakin təkrar sorğu bəzən başqasını qaytarır, ona görə \"sına\" bu qovşaq və ya klaster üçün linkləri yenidən istəyir. Klaster — bu verilənlər mərkəzidir: klg bağlantını qəbul edib susur, vla heç qəbul etmir.",
    },
    "hosts.clusters": {
        "ru": "Кластеры (ЦОД)", "en": "Clusters (data centres)",
        "tr": "Kümeler (veri merkezleri)", "kk": "Кластерлер (ЦОД)",
        "uz": "Klasterlar (maʼlumot markazlari)", "az": "Klasterlər (verilənlər mərkəzləri)",
    },
    "hosts.nodes": {
        "ru": "Узлы", "en": "Nodes", "tr": "Düğümler",
        "kk": "Түйіндер", "uz": "Tugunlar", "az": "Qovşaqlar",
    },
    "hosts.name": {
        "ru": "Узел", "en": "Node", "tr": "Düğüm",
        "kk": "Түйін", "uz": "Tugun", "az": "Qovşaq",
    },
    "hosts.files": {
        "ru": "Файлов", "en": "Files", "tr": "Dosya",
        "kk": "Файлдар", "uz": "Fayllar", "az": "Fayllar",
    },
    "hosts.size": {
        "ru": "Объём", "en": "Size", "tr": "Boyut",
        "kk": "Көлем", "uz": "Hajm", "az": "Həcm",
    },
    "hosts.seen": {
        "ru": "Видели", "en": "Seen", "tr": "Görülen",
        "kk": "Көрілген", "uz": "Koʻrilgan", "az": "Görülən",
    },
    "hosts.unavail": {
        "ru": "Недоступно", "en": "Unavailable", "tr": "Erişilemiyor",
        "kk": "Қолжетімсіз", "uz": "Ishlamaydi", "az": "Əlçatmaz",
    },
    "hosts.share": {
        "ru": "Живых", "en": "Alive", "tr": "Canlı",
        "kk": "Тірі", "uz": "Tirik", "az": "Diri",
    },
    "hosts.try": {
        "ru": "Попробовать", "en": "Try", "tr": "Dene",
        "kk": "Байқау", "uz": "Sinash", "az": "Sına",
    },
    "hosts.started": {
        "ru": "Запущено: {what}, {n} файлов. Ссылки запрошены заново.",
        "en": "Started: {what}, {n} files. Links requested again.",
        "tr": "Başladı: {what}, {n} dosya. Bağlantılar yeniden istendi.",
        "kk": "Іске қосылды: {what}, {n} файл. Сілтемелер қайта сұралды.",
        "uz": "Boshlandi: {what}, {n} fayl. Havolalar qaytadan soʻraldi.",
        "az": "Başladı: {what}, {n} fayl. Linklər yenidən istənildi.",
    },
    "left.title": {
        "ru": "Осталось взять", "en": "Left to take", "tr": "Kalan",
        "kk": "Алуға қалды", "uz": "Olish qoldi", "az": "Alınmalı qalan",
    },
    "left.now": {
        "ru": "облако отдаёт сейчас", "en": "cloud serves now",
        "tr": "şimdi veriliyor", "kk": "қазір беріледі",
        "uz": "hozir beriladi", "az": "indi verilir",
    },
    "left.unavailable": {
        "ru": "недоступно (может вернуться)", "en": "unavailable (may come back)",
        "tr": "erişilemiyor (dönebilir)", "kk": "қолжетімсіз (қайтуы мүмкін)",
        "uz": "ishlamaydi (qaytishi mumkin)", "az": "əlçatmaz (qayıda bilər)",
    },
    "left.gone": {
        "ru": "нет на сервере (404)", "en": "gone (404)",
        "tr": "sunucuda yok (404)", "kk": "серверде жоқ (404)",
        "uz": "serverda yoq (404)", "az": "serverdə yox (404)",
    },
    "left.unchecked": {
        "ru": "не проверено", "en": "unchecked", "tr": "denetlenmedi",
        "kk": "тексерілмеген", "uz": "tekshirilmagan", "az": "yoxlanmayıb",
    },
    "left.checked": {
        "ru": "по пробам, самая старая -- {when}", "en": "from probes, oldest {when}",
        "tr": "denetimlere göre, en eskisi {when}", "kk": "тексерулер бойынша, ең ескісі {when}",
        "uz": "tekshiruvlar boʻyicha, eng eskisi {when}", "az": "yoxlamalara görə, ən köhnəsi {when}",
    },
    "next.loop.lead": {
        "ru": "{n} {files} недоступны -- их стоит прогнать",
        "en": "{n} {files} unavailable -- worth re-running",
        "tr": "{n} {files} erişilemiyor -- yeniden denenmeli",
        "kk": "{n} {files} қолжетімсіз -- қайта өткізу керек",
        "uz": "{n} {files} ishlamaydi -- qayta oʻtish kerak",
        "az": "{n} {files} əlçatmaz -- yenidən keçmək lazım",
    },
    "next.loop.why": {
        "ru": "Недоступное возвращается, а исчезнувшее -- почти никогда. Прогон займёт около {hours} ч.",
        "en": "Unavailable files come back; missing ones almost never do. A pass takes about {hours} h.",
        "tr": "Erişilemeyenler geri döner, kaybolanlar neredeyse hiç dönmez. Tur yaklaşık {hours} saat sürer.",
        "kk": "Қолжетімсіздер қайтады, жоғалғандар -- ешқашан дерлік. Айналым шамамен {hours} сағат.",
        "uz": "Ishlamaydiganlar qaytadi, yoʻqolganlar -- deyarli hech qachon. Tur taxminan {hours} soat.",
        "az": "Əlçatmaz olanlar qayıdır, itənlər -- demək olar heç vaxt. Tur təxminən {hours} saat çəkir.",
    },
    "next.loop.btn": {
        "ru": "Прогнать оставшееся", "en": "Re-run what is left",
        "tr": "Kalanı yeniden dene", "kk": "Қалғанын қайта өткізу",
        "uz": "Qolganini qayta oʻtish", "az": "Qalanı yenidən keç",
    },
    "next.probe.lead": {
        "ru": "{n} {files} ещё не проверены", "en": "{n} {files} not checked yet",
        "tr": "{n} {files} henuz denetlenmedi", "kk": "{n} {files} әлі тексерілмеген",
        "uz": "{n} {files} hali tekshirilmagan", "az": "{n} {files} hele yoxlanilmayib",
    },
    "next.probe.why": {
        "ru": "Пока файл не проверен, неизвестно, отдаст ли его сервер и стоит ли на него рассчитывать.",
        "en": "Until a file is checked there is no telling whether the server serves it at all.",
        "tr": "Bir dosya denetlenmeden sunucunun onu verip vermeyecegi bilinemez.",
        "kk": "Файл тексерілмейінше, сервер оны берер-бермесі белгісіз.",
        "uz": "Fayl tekshirilmaguncha, server uni berishi yoki bermasligi nomalum.",
        "az": "Fayl yoxlanilmayana qeder serverin onu verib-vermeyecey bilinmir.",
    },
    "next.probe.btn": {
        "ru": "Проверить доступность", "en": "Check availability", "tr": "Erisimi denetle",
        "kk": "Қолжетімділікті тексеру", "uz": "Mavjudlikni tekshirish",
        "az": "Elcatanligi yoxla",
    },
    "next.stale.lead": {
        "ru": "{n} {files} проверены давно", "en": "{n} {files} checked long ago",
        "tr": "{n} {files} cok once denetlendi", "kk": "{n} {files} баяғыда тексерілген",
        "uz": "{n} {files} ancha oldin tekshirilgan", "az": "{n} {files} coxdan yoxlanilib",
    },
    "next.stale.why": {
        "ru": "Повреждённые ЦОДы возвращаются частями: недоступное вчера сегодня может отдаться.",
        "en": "Damaged datacentres come back in parts: yesterday's unavailable may serve today.",
        "tr": "Hasarli veri merkezleri parca parca donuyor: dun erisilemeyen bugun verilebilir.",
        "kk": "Зақымдалған ЦОД-тар бөліктеп оралады: кеше қолжетімсіз бүгін берілуі мүмкін.",
        "uz": "Shikastlangan markazlar qismlarga bolib qaytadi: kecha mavjud bolmagani bugun berilishi mumkin.",
        "az": "Zedelenmis merkezler hisse-hisse qayidir: dunen elcatmaz olan bu gun verile biler.",
    },
    "next.stale.btn": {
        "ru": "Перепроверить устаревшее", "en": "Recheck stale",
        "tr": "Eskimisleri yeniden denetle", "kk": "Ескіргенді қайта тексеру",
        "uz": "Eskirganni qayta tekshirish", "az": "Kohnelmisleri yeniden yoxla",
    },
    "next.archive.lead": {
        "ru": "{n} {files} спасено, но в одной копии",
        "en": "{n} {files} rescued, but in a single copy",
        "tr": "{n} {files} kurtarildi ama tek kopya",
        "kk": "{n} {files} құтқарылды, бірақ бір көшірмеде",
        "uz": "{n} {files} qutqarildi, lekin bitta nusxada",
        "az": "{n} {files} xilas edildi, amma tek nusxede",
    },
    "next.archive.why": {
        "ru": "Архив в 7z-томах -- второй носитель. Пока его нет, отказ одного диска уносит всё спасённое.",
        "en": "A 7z volume set is the second medium. Without it one disk failure takes everything rescued.",
        "tr": "7z birim seti ikinci ortamdir. O olmadan tek disk arizasi kurtarilan her seyi goturur.",
        "kk": "7z томдары -- екінші тасымалдағыш. Онсыз бір дискінің істен шығуы бәрін алып кетеді.",
        "uz": "7z jildlari -- ikkinchi tashuvchi. Usiz bitta disk nosozligi hammasini olib ketadi.",
        "az": "7z cildleri ikinci dasiyicidir. Onsuz bir diskin siradan cixmasi her seyi aparir.",
    },
    "next.archive.btn": {
        "ru": "Архивировать", "en": "Archive", "tr": "Arsivle",
        "kk": "Мұрағаттау", "uz": "Arxivlash", "az": "Arxivlesdir",
    },
    "next.autopilot.lead": {
        "ru": "{n} {files} сейчас не отдаются", "en": "{n} {files} do not serve now",
        "tr": "{n} {files} su anda verilmiyor", "kk": "{n} {files} қазір берілмейді",
        "uz": "{n} {files} hozir berilmayapti", "az": "{n} {files} hazirda verilmir",
    },
    "next.autopilot.why": {
        "ru": "Жать «перепроверить» вручную незачем: автопилот сам обойдёт их и заберёт ожившее.",
        "en": "No need to press recheck by hand: autopilot walks them and takes back what returns.",
        "tr": "Elle yeniden denetlemeye gerek yok: otomatik pilot dolasip geri donenleri alir.",
        "kk": "Қолмен қайта тексерудің қажеті жоқ: автопилот өзі аралап, оралғанын алады.",
        "uz": "Qolda qayta tekshirish shart emas: avtopilot ozi aylanib, qaytganini oladi.",
        "az": "Elle yeniden yoxlamaga ehtiyac yoxdur: avtopilot ozu gezib qayidanlari goturur.",
    },
    "next.autopilot.btn": {
        "ru": "Включить автопилот", "en": "Turn on autopilot", "tr": "Otomatik pilotu ac",
        "kk": "Автопилотты қосу", "uz": "Avtopilotni yoqish", "az": "Avtopilotu ac",
    },
    "next.done.lead": {
        "ru": "Пока делать нечего", "en": "Nothing to do right now",
        "tr": "Su an yapilacak bir sey yok", "kk": "Әзірге істейтін ештеңе жоқ",
        "uz": "Hozircha qiladigan ish yoq", "az": "Hazirda gorulesi is yoxdur",
    },
    "next.done.why": {
        "ru": "Всё описано, проверено и спасено. Загляни позже: доступность меняется, и недоступное может ожить.",
        "en": "Everything is inventoried, checked and rescued. Come back later: availability shifts.",
        "tr": "Her sey envanterlendi, denetlendi ve kurtarildi. Sonra ugrayin: erisilebilirlik degisir.",
        "kk": "Бәрі тізімделді, тексерілді және құтқарылды. Кейінірек қараңыз: қолжетімділік өзгереді.",
        "uz": "Hammasi royxatga olindi, tekshirildi va qutqarildi. Keyinroq qarang: mavjudlik ozgaradi.",
        "az": "Her sey siyahiya alinib, yoxlanilib ve xilas edilib. Sonra baxin: elcatanliq deyisir.",
    },

    "grp.inventory": {"ru": "Опись", "en": "Inventory", "tr": "Envanter",
                      "kk": "Тізім", "uz": "Roʻyxat", "az": "Siyahı"},
    "grp.access": {"ru": "Доступность", "en": "Availability", "tr": "Erişim",
                   "kk": "Қолжетімділік", "uz": "Mavjudlik", "az": "Əlçatanlıq"},
    "grp.rescue": {"ru": "Спасение", "en": "Rescue", "tr": "Kurtarma",
                   "kk": "Құтқару", "uz": "Qutqarish", "az": "Xilasetmə"},

    "now.title": {"ru": "Сейчас", "en": "Now", "tr": "Şu anda",
                  "kk": "Қазір", "uz": "Hozir", "az": "İndi"},
    "next.title": {"ru": "Что дальше", "en": "What next", "tr": "Sırada ne var",
                   "kk": "Әрі қарай не", "uz": "Keyin nima", "az": "Növbəti addım"},
    "next.autopilot.done": {
        "ru": "Автопилот включён: сам перепроверит недоступное и заберёт ожившее.",
        "en": "Autopilot is on: it will recheck unavailable files and take back what returns.",
        "tr": "Otomatik pilot açık: erişilemezleri yeniden denetler ve geri dönenleri alır.",
        "kk": "Автопилот қосулы: қолжетімсізді қайта тексеріп, оралғанын алады.",
        "uz": "Avtopilot yoqilgan: mavjud emaslarni qayta tekshiradi va qaytganini oladi.",
        "az": "Avtopilot aktivdir: əlçatmazları yenidən yoxlayıb qayıdanları götürəcək.",
    },
    "totals.title": {"ru": "Итоги", "en": "Totals", "tr": "Toplam",
                     "kk": "Қорытынды", "uz": "Yakun", "az": "Yekun"},

    "tile.available": {"ru": "доступно", "en": "available", "tr": "erişilebilir",
                       "kk": "қолжетімді", "uz": "mavjud", "az": "əlçatan"},
    "tile.unavailable": {"ru": "недоступно", "en": "unavailable", "tr": "erişilemez",
                         "kk": "қолжетімсіз", "uz": "mavjud emas", "az": "əlçatmaz"},
    "tile.unchecked": {"ru": "не проверено", "en": "unchecked", "tr": "denetlenmedi",
                       "kk": "тексерілмеген", "uz": "tekshirilmagan",
                       "az": "yoxlanılmayıb"},
    "tile.wasFiles": {
        "ru": "Было файлов", "en": "Files in inventory", "tr": "Envanterde dosya",
        "kk": "Тізімдегі файл", "uz": "Roʻyxatdagi fayl", "az": "Siyahıda fayl",
    },
    "tile.deletedByUs": {
        "ru": "удалено нами", "en": "deleted by us", "tr": "biz sildik",
        "kk": "біз жойдық", "uz": "biz oʻchirdik", "az": "biz sildik",
    },
    "tile.neverTaken": {
        "ru": "так и не взяли", "en": "never taken", "tr": "hiç alınmadı",
        "kk": "ала алмадық", "uz": "ola olmadik", "az": "ala bilmədik",
    },
    "tile.onDisk": {
        "ru": "на диске", "en": "on disk", "tr": "diskte",
        "kk": "дискіде", "uz": "diskda", "az": "diskdə",
    },
    "tile.missingLocal": {
        "ru": "пропало с диска", "en": "missing from disk", "tr": "diskten kayıp",
        "kk": "дискіден жоғалды", "uz": "diskdan yoʻqoldi", "az": "diskdon itdi",
    },
    "tile.vanished": {
        "ru": "удалено тобой в вебе", "en": "you deleted in web",
        "tr": "buluttan kayboldu", "kk": "бұлттан жоғалды",
        "uz": "bulutdan yoqoldi", "az": "buluddan itdi",
    },
    "tile.salvaged": {
        "ru": "с дырками", "en": "with holes", "tr": "delikli",
        "kk": "тесіктері бар", "uz": "teshikli", "az": "deşikli",
    },
    "tile.fixed": {
        "ru": "докачано полностью", "en": "completed later",
        "tr": "sonradan tamamlandı", "kk": "кейін толықтырылды",
        "uz": "keyin toʻldirildi", "az": "sonradan tamamlandı",
    },
    "tile.gone": {"ru": "нет на сервере", "en": "gone from server",
                  "tr": "sunucuda yok", "kk": "серверде жоқ",
                  "uz": "serverda yoʻq", "az": "serverdə yoxdur"},

    "legend.dot": {"ru": "Точка:", "en": "Dot:", "tr": "nokta:",
                   "kk": "нүкте:", "uz": "nuqta:", "az": "nöqtə:"},
    "legend.ok": {"ru": "отдаётся", "en": "serves", "tr": "veriliyor",
                  "kk": "беріледі", "uz": "beriladi", "az": "verilir"},
    "legend.unavailable": {"ru": "не отдаётся", "en": "does not serve",
                           "tr": "verilmiyor", "kk": "берілмейді",
                           "uz": "berilmaydi", "az": "verilmir"},
    "legend.gone": {"ru": "нет на сервере", "en": "gone", "tr": "sunucuda yok",
                    "kk": "серверде жоқ", "uz": "serverda yoʻq",
                    "az": "serverdə yoxdur"},
    "legend.unchecked": {"ru": "не проверено", "en": "unchecked",
                         "tr": "denetlenmedi", "kk": "тексерілмеген",
                         "uz": "tekshirilmagan", "az": "yoxlanılmayıb"},
    "legend.stale": {
        "ru": "бледная — проверено давно", "en": "pale — checked long ago",
        "tr": "soluk — çok önce denetlendi", "kk": "бозғылт — баяғыда тексерілген",
        "uz": "oqish — ancha oldin tekshirilgan", "az": "solğun — çoxdan yoxlanılıb",
    },
    "legend.saved": {"ru": "спасён", "en": "rescued", "tr": "kurtarıldı",
                     "kk": "құтқарылды", "uz": "qutqarildi", "az": "xilas edildi"},
    "legend.arch": {"ru": "в архиве", "en": "archived", "tr": "arşivde",
                    "kk": "мұрағатта", "uz": "arxivda", "az": "arxivdə"},
    "legend.deleted": {"ru": "убран из облака", "en": "removed from cloud",
                       "tr": "buluttan silindi", "kk": "бұлттан жойылды",
                       "uz": "bulutdan oʻchirildi", "az": "buluddan silindi"},

    "btn.download.empty": {
        "ru": "Сначала отметь галочками, что качать: папку или отдельные файлы",
        "en": "First tick what to download: a folder or individual files",
        "tr": "Önce neyin indirileceğini işaretleyin: bir klasör veya dosyalar",
        "kk": "Алдымен нені жүктейтінін белгілеңіз: қалта немесе жеке файлдар",
        "uz": "Avval nimani yuklashni belgilang: papka yoki alohida fayllar",
        "az": "Əvvəlcə nəyi endirəcəyinizi işarələyin: qovluq və ya ayrı fayllar",
    },

    "btn.previews": {
        "ru": "Добрать превью", "en": "Fetch previews", "tr": "Önizlemeleri al",
        "kk": "Нобайларды алу", "uz": "Koʻrinishlarni olish", "az": "Önizləmələri al",
    },
    "btn.adopt": {
        "ru": "Взять из папки клиента", "en": "Adopt from client folder",
        "tr": "İstemci klasöründen al", "kk": "Клиент қалтасынан алу",
        "uz": "Klient pappkasidan olish", "az": "Müştəri qovluğundan al",
    },
    "btn.adopt.title": {
        "ru": "Забрать жёсткими ссылками файлы, которые клиент Диска когда-то синхронизировал",
        "en": "Take files the Disk client once synced, via hard links",
        "tr": "Disk istemcisinin bir zamanlar senkronladığı dosyaları sabit bağlantıyla al",
        "kk": "Disk клиенті бір кезде синхрондаған файлдарды қатты сілтемепен алу",
        "uz": "Disk klienti bir paytda sinxronlagan fayllarni qattiʻ havola bilan olish",
        "az": "Disk müştərisinin bir vaxtlar sinxronlaşdırdığı faylları sərt bağlantı ilə al",
    },
    "scan.pending": {
        "ru": "прерванная опись: в очереди {n} {folders}", "en": "interrupted inventory: {n} {folders} queued",
        "tr": "kesilen envanter: sırada {n} {folders}", "kk": "үзілген тізімдеу: кезекте {n} {folders}",
        "uz": "uzilgan roʻyxatga olish: navbatda {n} {folders}", "az": "kəsilən siyahı: növbədə {n} {folders}",
    },
    "scan.pending.title": {
        "ru": "Прошлый обход облака не дошёл до конца -- новый продолжится с этого места, а не с корня",
        "en": "The last walk did not finish -- the new one continues from there, not from the root",
        "tr": "Son gezinme bitmedi -- yenisi baştan değil, oradan devam eder",
        "kk": "Соңғы аралау бітпеді -- жаңасы басынан емес, сол жерден жалғасады",
        "uz": "Oxirgi aylanib chiqish tugamadi -- yangisi boshidan emas, oʻsha joydan davom etadi",
        "az": "Son gəzintə bitmədi -- yenisi əvvəldən deyil, oradan davam edəcək",
    },
    "scan.restart": {
        "ru": "начать заново", "en": "start over", "tr": "baştan başla",
        "kk": "басынан бастау", "uz": "boshidan boshlash", "az": "əvvəldən başla",
    },
    "scan.restart.title": {
        "ru": "Игнорировать сохранённую очередь папок и обойти облако с корня",
        "en": "Ignore the saved folder queue and walk the cloud from the root",
        "tr": "Kaydedilen klasör kuyruğunu yok say, bulutu baştan gez",
        "kk": "Сақталған қалта кезегін елемей, бұлтты басынан аралау",
        "uz": "Saqlangan papka navbatini eʼtiborsiz qoldirib, bulutni boshidan aylash",
        "az": "Yadda saxlanmış qovluq növbəsini rədd et, buludu əvvəldən gəz",
    },
    "adopt.noFolder": {
        "ru": "Папка клиента Яндекс.Диска не найдена. Укажи её: DRYDOCK_YADISK",
        "en": "Yandex.Disk client folder not found. Set DRYDOCK_YADISK",
        "tr": "Yandex.Disk istemci klasörü bulunamadı: DRYDOCK_YADISK",
        "kk": "Yandex.Disk клиент қалтасы табылмады: DRYDOCK_YADISK",
        "uz": "Yandex.Disk klient pappkasi topilmadi: DRYDOCK_YADISK",
        "az": "Yandex.Disk müştəri qovluğu tapılmadı: DRYDOCK_YADISK",
    },
    "adopt.nothing": {
        "ru": "В локальной папке нечего брать: всё снесённое уже спасено",
        "en": "Nothing to take in the local folder: everything there is already saved",
        "tr": "Yerel klasörde alınacak bir şey yok:Kayıtlı olan her şey çoktan kurtarıldı",
        "kk": "Жергілікті қалтада алатын еш нәрсе жоқ: сақталғанның бәрі құтқарылған",
        "uz": "Mahalliy pappkada olinadigan hech narsa yoʻq: saqlanganni hammasi qutqarilgan",
        "az": "Yerli qovluqda alınacaq heç nə yoxdur: qeydə alınmışın hamısı xilas edilib",
    },
    "adopt.body": {
        "ru": "В папке клиента лежит <b>{files}</b> {n} на {size} из тех, что ещё не спасены.",
        "en": "The client folder holds <b>{files}</b> {n} ({size}) of files not saved yet.",
        "tr": "İstemci klasöründe henüz kurtarılmamış <b>{files}</b> {n} ({size}) var.",
        "kk": "Клиент қалтасында әлі құтқарылмаған <b>{files}</b> {n} ({size}) жатыр.",
        "uz": "Klient pappkasida hali qutqarilmagan <b>{files}</b> {n} ({size}) bor.",
        "az": "Müştəri qovluğunda hələ xilas olunmamış <b>{files}</b> {n} ({size}) var.",
    },
    "adopt.title": {
        "ru": "Взять из папки клиента", "en": "Adopt from client folder",
        "tr": "İstemci klasöründen al", "kk": "Клиент қалтасынан алу",
        "uz": "Klient pappkasidan olish", "az": "Müştəri qovluğundan al",
    },
    "adopt.onlyWarn": {
        "ru": "Из них <b>{n}</b> недоступны в облаке -- эта папка единственное место, где они ещё есть.",
        "en": "<b>{n}</b> of them are unavailable in the cloud -- this folder is the only place they still exist.",
        "tr": "Bunlardan <b>{n}</b> tanesi bulutta yok -- bu klasör onların var olduğu tek yer.",
        "kk": "Олардың <b>{n}</b>-ы бұлтта жоқ -- бұл қалта олардың бар қалған жалғыз орны.",
        "uz": "Ulardan <b>{n}</b> tasi bulutda yoʻq -- bu papka ular hali mavjud boʻlgan yagona joy.",
        "az": "Bunlardan <b>{n}</b> dənəsi bulutda yoxdur -- bu qovluq onların hələ var olduğu tək yer.",
    },
    "adopt.states": {
        "ru": "По последней проверке: {list}", "en": "By the last check: {list}",
        "tr": "Son denetime göre: {list}", "kk": "Соңғы тексеру бойынша: {list}",
        "uz": "Oxirgi tekshiruv boʻyicha: {list}", "az": "Son yoxlamaya görə: {list}",
    },
    "adopt.moveNote": {
        "ru": "Файлы будут <b>перенесены</b>: из папки клиента они уходят, в нашей остаются. Клиент Диска увидит пропажу и уберёт их из облака сам.",
        "en": "Files will be <b>moved</b>: they leave the client folder and stay in ours. The Disk client will notice and remove them from the cloud itself.",
        "tr": "Dosyalar <b>taşınacak</b>: istemci klasöründen çıkıp bizimkinde kalacak. Disk istemcisi kaybı görüp buluttan kendisi kaldıracak.",
        "kk": "Файлдар <b>көшіріледі</b>: клиент қалтасынан кетіп, біздің қалтада қалады. Disk клиенті жоғалғанын байқап, бұлттан өзі алып тастайды.",
        "uz": "Fayllar <b>koʻchiriladi</b>: klient pappkasidan chiqib, biznikida qoladi. Disk klienti yoʻqotishni koʻrib, bulutdan oʻzi olib tashlaydi.",
        "az": "Fayllar <b>köçürüləcək</b>: müştəri qovluğundan çıxıb bizimkində qalacaq. Disk müştərisi itkini görüb bulutdan özü siləcək.",
    },
    "adopt.linked": {
        "ru": "Ещё <b>{n}</b> ({size}) взяты прежним механизмом жёсткими ссылками: они лежат и в папке клиента, и в облаке. Доделаю перенос — уберу запись из папки клиента и облачную копию.",
        "en": "<b>{n}</b> more ({size}) were taken by the old hard-link mechanism: they sit both in the client folder and in the cloud. I will finish the move — remove the client-folder entry and the cloud copy.",
        "tr": "Önceki sabit bağlantı mekanizmasıyla alınmış <b>{n}</b> dosya ({size}) hem istemci klasöründe hem bulutta. Taşımayı bitireceğim — istemci klasöründeki kaydı ve bulut kopyasını kaldıracağım.",
        "kk": "Бұрынғы қатты сілтеме механизмімен алынған <b>{n}</b> файл ({size}) клиент қалтасында да, бұлтта да бар. Көшіруді аяқтаймын — клиент қалтасындағы жазбаны және бұлт көшірмесін жоямын.",
        "uz": "Avvalgi qattiʻ havola mexanizmi bilan olingan <b>{n}</b> fayl ({size}) klient pappkasida ham, bulutda ham bor. Koʻchirishni tugataman — klient pappkasidagi yozuvni va bulut nusxasini olib tashlayman.",
        "az": "Əvvəlki sərt bağlantı mexanizmi ilə alınmış <b>{n}</b> fayl ({size}) həm müştəri qovluğunda, həm bulutdadır. Köçürməni bitirəcəyəm — müştəri qovluğundakı qeydi və bulut nüsxəsini siləcəyəm.",
    },
    "adopt.delCloud": {
        "ru": "удалить из облака после сверки хеша",
        "en": "delete from the cloud after hash verification",
        "tr": "özet denetiminden sonra buluttan sil",
        "kk": "хэш тексерісінен кейін бұлттан жою",
        "uz": "xesh tekshiruvidan keyin bulutdan oʻchirish",
        "az": "heş yoxlamasından sonra bulutdan sil",
    },
    "adopt.delWarn": {
        "ru": "Удаляются только файлы, у которых хеш сошёлся с сообщённым Яндексом, — то есть те, что точно есть на нашем диске. Непроверенное остаётся в облаке. Удаление идёт мимо Корзины и необратимо.",
        "en": "Only files whose hash matched the one Yandex reported are deleted — that is, those certainly present on our disk. Unverified ones stay in the cloud. Deletion skips the Trash and cannot be undone.",
        "tr": "Yalnızca özeti Yandex'in bildirdiğiyle tutan dosyalar silinir — yani diskimizde kesin olanlar. Doğrulanmayanlar bulutta kalır. Silme Çöp Kutusu'nu atlar ve geri alınamaz.",
        "kk": "Тек хэші Яндекс хабарлағанмен сәйкес келген файлдар жойылады — яғни біздің дискіде нақты барлар. Тексерілмеген бұлтта қалады. Жою Себетті айналып өтеді және қайтарылмайды.",
        "uz": "Faqat xeshi Yandex aytganiga mos kelgan fayllar oʻchiriladi — yaʼni diskimizda aniq borlari. Tekshirilmaganlari bulutda qoladi. Oʻchirish Savatni chetlab oʻtadi va qaytarilmaydi.",
        "az": "Yalnız heşi Yandex-in bildirdiyi ilə üst-üstə düşən fayllar silinir — yəni diskimizdə mütləq olanlar. Yoxlanılmamışlar bulutda qalır. Silmə Zibil Qutusunu keçir və geri qaytarılmır.",
    },
    "adopt.go": {
        "ru": "Взять ({n})", "en": "Adopt ({n})", "tr": "Al ({n})",
        "kk": "Алу ({n})", "uz": "Olish ({n})", "az": "Al ({n})",
    },
    "btn.mirror": {
        "ru": "Учесть перенесённое", "en": "Register copied files",
        "tr": "Kopyalananları kaydet", "kk": "Көшірілгендерді есепке алу",
        "uz": "Koʻchirilganlarni hisobga olish", "az": "Köçürülənləri qeydə al",
    },
    "btn.mirror.title": {
        "ru": "Учесть файлы, положенные в папку спасения руками — их не видно ни в дереве, ни в итогах",
        "en": "Register files placed into the save folder by hand — invisible to the tree and totals",
        "tr": "Kurtarma klasörüne elle konan dosyaları kaydet — ağaçta ve toplamlarda görünmezler",
        "kk": "Сақтау қалтасына қолмен салынған файлдарды есепке алу — ағашта да, жиынтықта да көрінбейді",
        "uz": "Saqlash pappkasiga qoʻl bilan qoʻyilgan fayllarni hisobga olish — daraxtda ham, jami hisobda ham koʻrinmaydi",
        "az": "Xilas qovluğuna əllə qoyulan faylları qeydə al — ağaçda da, cəmlərdə də görünmür",
    },
    "mirror.title": {
        "ru": "Учёт перенесённого вручную", "en": "Register hand-copied files",
        "tr": "Elle kopyalananların kaydı", "kk": "Қолмен көшірілгендерді есепке алу",
        "uz": "Qoʻl bilan koʻchirilganlarni hisobga olish", "az": "Əllə köçürülənlərin qeydi",
    },
    "mirror.body": {
        "ru": "В папке спасения лежит <b>{files}</b> {n} ({size}) в {folders} папках, которых программа не знает.",
        "en": "The save folder holds <b>{files}</b> {n} ({size}) in {folders} folders the program does not know about.",
        "tr": "Kurtarma klasöründe programın bilmediği <b>{files}</b> {n} ({size}), {folders} klasörde.",
        "kk": "Сақтау қалтасында бағдарлама білмейтін <b>{files}</b> {n} ({size}), {folders} қалтада.",
        "uz": "Saqlash pappkasida dastur bilmaydigan <b>{files}</b> {n} ({size}), {folders} pappkada.",
        "az": "Xilas qovluğunda proqramın bilmədiyi <b>{files}</b> {n} ({size}), {folders} qovluqda.",
    },
    "mirror.withMeta": {
        "ru": " Из них <b>{n}</b> есть в облачной описи — у них сверим хеши.",
        "en": " <b>{n}</b> of them are in the cloud inventory — their hashes will be checked.",
        "tr": " Bunlardan <b>{n}</b> tanesi bulut envanterinde — özetleri denetlenecek.",
        "kk": " Олардың <b>{n}</b>-ы бұлт тізімінде — хэштерін тексереміз.",
        "uz": " Ulardan <b>{n}</b> tasi bulut roʻyxatida — xeshlarini tekshiramiz.",
        "az": " Bunlardan <b>{n}</b> dənəsi bulut siyahısındadır — heşlər yoxlanılacaq.",
    },
    "mirror.noMeta": {
        "ru": " Ни одного нет в облачной описи — хеши сверять не с чем, будут учтены как «непроверенные».",
        "en": " None are in the cloud inventory — nothing to check hashes against; they will be registered as unverified.",
        "tr": " Hiçbiri bulut envanterinde değil — karşılaştırılacak özet yok; «doğrulanmamış» olarak kaydedilecek.",
        "kk": " Бірде-біреуі бұлт тізімінде жоқ — салыстырар хэш жоқ, «тексерілмеген» болады.",
        "uz": " Birortasi ham bulut roʻyxatida yoʻq — solishtirish uchun xesh yoʻq, «tekshirilmagan» boʻladi.",
        "az": " Heç biri bulut siyahısında deyil — müqayisə üçün heş yoxdur, «yoxlanılmamış» olacaq.",
    },
    "mirror.how": {
        "ru": "Файлы уже на диске — ничего не копируется: программа лишь узнаёт о них и начнёт считать в итогах, дереве и архивах.",
        "en": "Files are already on disk — nothing is copied: the program just learns about them and starts counting them in totals, tree and archives.",
        "tr": "Dosyalar diskte zaten var — hiçbir şey kopyalanmaz: program yalnızca onları tanır ve toplam, ağaç ve arşivlerde saymaya başlar.",
        "kk": "Файлдар дискіде бар екен — еш нәрсе көшірілмейді: бағдарлама оларды таниды да жиынтық, ағаш және мұрағаттарда санай бастайды.",
        "uz": "Fayllar diskda bor — hech narsa koʻchirilmaydi: dastur ularni tanib, jami hisob, daraxt va arxivlarda sanay boshlaydi.",
        "az": "Fayllar diskdədir — heç nə köçürülmür: proqram onları tanıyır və cəmlər, ağac və arxivlərdə saymağa başlayır.",
    },
    "mirror.nothing": {
        "ru": "В папке спасения нет файлов мимо программы — всё учтено",
        "en": "No files bypassing the program in the save folder — everything is registered",
        "tr": "Kurtarma klasöründe program dışı dosya yok — her şey kayıtlı",
        "kk": "Сақтау қалтасында бағдарламадан тыс файл жоқ — бәрі есепте",
        "uz": "Saqlash pappkasida dasturdan tashqari fayl yoʻq — hammasi hisobda",
        "az": "Xilas qovluğunda proqramdan kənar fayl yoxdur — hər şey qeydə alınıb",
    },
    "mirror.go": {
        "ru": "Учесть ({n})", "en": "Register ({n})", "tr": "Kaydet ({n})",
        "kk": "Есепке алу ({n})", "uz": "Hisobga olish ({n})", "az": "Qeydə al ({n})",
    },
    "btn.settings": {
        "ru": "Настройки", "en": "Settings", "tr": "Ayarlar",
        "kk": "Баптаулар", "uz": "Sozlamalar", "az": "Tənzimləmələr",
    },
    "btn.settings.title": {
        "ru": "Куда программа спасает коллекцию",
        "en": "Where the program saves the collection",
        "tr": "Program koleksiyonu nereye kaydediyor",
        "kk": "Бағдарлама жинақты қайда сақтайды",
        "uz": "Dastur toʻplamni qayga saqlaydi",
        "az": "Proqram kolleksiyanı harada saxlayır",
    },
    "set.title": {
        "ru": "Настройки", "en": "Settings", "tr": "Ayarlar",
        "kk": "Баптаулар", "uz": "Sozlamalar", "az": "Tənzimləmələr",
    },
    "set.body": {
        "ru": "Папка спасения: зеркало облака, опись, превью, архивы и база состояния.",
        "en": "Save folder: cloud mirror, inventory, previews, archives and the state database.",
        "tr": "Kurtarma klasörü: bulut aynası, envanter, önizlemeler, arşivler ve durum veritabanı.",
        "kk": "Сақтау қалтасы: бұлт айнасы, тізімдеу, нобайлар, мұрағаттар және күй базасы.",
        "uz": "Saqlash pappkasi: bulut nusxasi, roʻyxat, koʻrinishlar, arxivlar va holat bazasi.",
        "az": "Xilas qovluğu: bulut əksi, siyahı, önizləmələr, arxivlər və vəziyyət bazası.",
    },
    "set.db": {
        "ru": "Сейчас база состояния: {db}", "en": "State database now: {db}",
        "tr": "Durum veritabanı şu anda: {db}", "kk": "Күй базасы қазір: {db}",
        "uz": "Holat bazasi hozir: {db}", "az": "Vəziyyət bazası indi: {db}",
    },
    "set.envLock": {
        "ru": "Корень задан переменной окружения DRYDOCK_ROOT — она сильнее выбора в окне. Сначала убери её из ярлыка или командной строки.",
        "en": "Root is set by the DRYDOCK_ROOT environment variable — stronger than the UI choice. Remove it from the shortcut or command line first.",
        "tr": "Kök, DRYDOCK_ROOT ortam değişkeniyle belirlenmiş — arayüz seçiminden güçlü. Önce kısayoldan veya komut satırından kaldırın.",
        "kk": "Түпкі каталог DRYDOCK_ROOT айнымалысымен белгіленген — терезедегі таңдаудан күшті. Алдымен оны жарлықтан не команжа жолынан алып таста.",
        "uz": "Ildiz katalog DRYDOCK_ROOT muhit oʻzgaruvchisi bilan belgilangan — oynadagi tanlovdan kuchli. Avval uni yorliqdan yoki buyruq qatoridan olib tashla.",
        "az": "Kök kataloq DRYDOCK_ROOT mühit dəyişəni ilə təyin edilib — pəncərədəki seçimdən güclüdür. Əvvəlcə onu qısayoldan və ya əmrlər sətrindən çıxar.",
    },
    "set.restart": {
        "ru": "Применится при следующем запуске. Уже спасённое останется на месте: переносить 22 ГБ файлов и базу — решение отдельное, программа сама ничего не двигает.",
        "en": "Takes effect on the next launch. Already-saved data stays where it is: moving 22 GB of files and the database is a separate decision — the program moves nothing on its own.",
        "tr": "Sonraki başlatmada etkin olur. Kurtarılanlar yerinde kalır: 22 GB dosyanın taşınması ayrı bir karardır — program kendi başına hiçbir şeyi taşımaz.",
        "kk": "Келесі іске қосқанда күшіне енеді. Сақталған өз орнында қалады: 22 ГБ файлды көшіру — бөлек шешім, бағдарлама өзі еш нәрсе жылжытпайды.",
        "uz": "Keyingi ishga tushirishda kuchga kiradi. Saqlangani oʻz joyida qoladi: 22 GB faylni koʻchirish — alohida qaror, dastur oʻzi hech narsani koʻchirmaydi.",
        "az": "Növbəti işə salınanda qüvvəyə minir. Xilas edilənlər yerində qalar: 22 GB faylın köçürülməsi — ayrıca qərardır, proqram özü heç nə köçürmür.",
    },
    "set.saved": {
        "ru": "Корень спасения: {root}", "en": "Save root: {root}",
        "tr": "Kurtarma kökü: {root}", "kk": "Сақтау түпкісі: {root}",
        "uz": "Saqlash ildizi: {root}", "az": "Xilas kökü: {root}",
    },
    "btn.save": {
        "ru": "Сохранить", "en": "Save", "tr": "Kaydet",
        "kk": "Сақтау", "uz": "Saqlash", "az": "Yadda saxla",
    },
    "btn.onlyUnsaved": {
        "ru": "Только нескачанное", "en": "Unsaved only", "tr": "Yalnızca kurtarılmamış",
        "kk": "Тек сақталмаған", "uz": "Faqat saqlanmagan", "az": "Yalnız xilas olunmamış",
    },
    "btn.onlyUnsaved.title": {
        "ru": "Показывать только папки, где есть файлы без локальной копии; выкачанные папки из вида уходят",
        "en": "Show only folders that have files without a local copy; fully downloaded folders leave the view",
        "tr": "Yalnızca yerel kopyası olmayan dosyaları olan klasörleri göster; indirilen klasörler görünümden çıkar",
        "kk": "Тек жергілікті көшірмесі жоқ файлдары бар қалталарды көрсету; жүктелген қалталар көріністен кетеді",
        "uz": "Faqat mahalliy nusxasi yoʻq fayllari bor pappkalarni koʻrsatish; yuklab olingan pappkalar koʻrinishdan ketadi",
        "az": "Yalnız yerli nüsxəsi olmayan faylları olan qovluqları göstər; endirilən qovluqlar görünüşdən çıxır",
    },
    "btn.onlyUnsaved.on": {
        "ru": "Показать всё дерево (щёлкни, чтобы выйти из режима)",
        "en": "Show the whole tree (click to leave the mode)",
        "tr": "Tüm ağacı göster (moddan çıkmak için tıkla)",
        "kk": "Бүкіл ағашты көрсету (режимнен шығу үшін бас)",
        "uz": "Butun daraxtni koʻrsatish (rejimdan chiqish uchun bosing)",
        "az": "Bütün ağacı göstər (rejimdən çıxmaq üçün kliklə)",
    },
    "btn.onlyUnsaved.off": {
        "ru": "Только нескачанное ✓", "en": "Unsaved only ✓",
        "tr": "Yalnızca kurtarılmamış ✓", "kk": "Тек сақталмаған ✓",
        "uz": "Faqat saqlanmagan ✓", "az": "Yalnız xilas olunmamış ✓",
    },
    "btn.previews.title": {
        "ru": "Добрать превью для файлов, у которых их ещё нет",
        "en": "Fetch previews for files that do not have one yet",
        "tr": "Henüz önizlemesi olmayan dosyalar için önizleme al",
        "kk": "Нобайы жоқ файлдар үшін нобай алу",
        "uz": "Hali koʻrinishi yoʻq fayllar uchun koʻrinish olish",
        "az": "Hələ önizləməsi olmayan fayllar üçün önizləmə al",
    },
    "btn.probe": {
        "ru": "Проверить доступность", "en": "Check availability",
        "tr": "Erişilebilirliği denetle", "kk": "Қолжетімділікті тексеру",
        "uz": "Mavjudlikni tekshirish", "az": "Əlçatanlığı yoxla",
    },
    "btn.probe.title": {
        "ru": "Проверить, отдаёт ли хранилище первый байт. Ничего не скачивается",
        "en": "Check whether storage returns the first byte. Nothing is downloaded",
        "tr": "Depolamanın ilk baytı verip vermediğini denetler. Hiçbir şey indirilmez",
        "kk": "Қойма бірінші байтты беретінін тексеру. Ештеңе жүктелмейді",
        "uz": "Ombor birinchi baytni berishini tekshirish. Hech narsa yuklanmaydi",
        "az": "Anbarın ilk baytı verib-vermədiyini yoxlayır. Heç nə endirilmir",
    },
    "probe.scope.title": {
        "ru": "Что проверять", "en": "What to check", "tr": "Ne denetlenecek",
        "kk": "Нені тексеру", "uz": "Nimani tekshirish", "az": "Nəyi yoxlamalı",
    },
    "probe.scope.selection": {
        "ru": "выбранное", "en": "selection", "tr": "seçilenler",
        "kk": "таңдалғандар", "uz": "tanlanganlar", "az": "seçilmişlər",
    },
    "probe.scope.unchecked": {
        "ru": "всё непроверенное", "en": "everything unchecked",
        "tr": "denetlenmemiş her şey", "kk": "тексерілмегеннің бәрі",
        "uz": "tekshirilmagan hammasi", "az": "yoxlanılmamış hər şey",
    },
    "probe.scope.unavailable": {
        "ru": "перепроверить недоступное", "en": "recheck unavailable",
        "tr": "erişilemezleri yeniden denetle", "kk": "қолжетімсізді қайта тексеру",
        "uz": "mavjud emaslarni qayta tekshirish", "az": "əlçatmazları yenidən yoxla",
    },
    "probe.scope.all": {
        "ru": "всё заново", "en": "everything again", "tr": "her şeyi yeniden",
        "kk": "бәрін қайтадан", "uz": "hammasini qaytadan", "az": "hər şeyi yenidən",
    },
    "loop.title": {
        "ru": "Качать по кругу", "en": "Download on repeat", "tr": "Dongusel indirme",
        "kk": "Шеңбер бойынша жүктеу", "uz": "Aylanma yuklash", "az": "Dövrə ilə endirmə",
    },
    "loop.plan": {
        "ru": "<p>В круге <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "en": "<p>The round holds <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "tr": "<p>Turda <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "kk": "<p>Шеңберде <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "uz": "<p>Aylanada <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "az": "<p>Dövrədə <b>{n}</b> {files}, <b>{size}</b>.</p>",
    },
    "loop.why": {
        "ru": "<p>Проба не запускается: попытка скачать и есть проверка, причём честнее -- она читает файл целиком, а не первый байт. Очередь пересобирается каждый круг, поэтому спасённое выпадает само и круги укорачиваются.</p><p>Работа не кончится сама: останови её кнопкой «стоп» в списке задач.</p>",
        "en": "<p>No probing: the download attempt is the check, and a truer one — it reads the whole file, not the first byte. The queue is rebuilt every round, so what is rescued drops out and rounds get shorter.</p><p>It will not end by itself: stop it with the job list's stop button.</p>",
        "tr": "<p>Yoklama yok: indirme denemesi zaten denetimdir ve daha dogrudur. Kuyruk her turda yeniden kurulur.</p><p>Kendiliginden bitmez: gorev listesindeki durdur dugmesiyle durdurun.</p>",
        "kk": "<p>Сынақ жүргізілмейді: жүктеу әрекетінің өзі тексеру, әрі шынайырақ. Кезек әр шеңберде қайта жиналады.</p><p>Өзі бітпейді: тапсырмалар тізіміндегі «стоп» батырмасымен тоқтатыңыз.</p>",
        "uz": "<p>Sinov oʻtkazilmaydi: yuklash urinishining oʻzi tekshiruv va rostroq. Navbat har aylanada qayta yigʻiladi.</p><p>Oʻzi tugamaydi: vazifalar roʻyxatidagi toʻxtatish tugmasi bilan toʻxtating.</p>",
        "az": "<p>Yoxlama aparılmır: endirmə cəhdinin özü yoxlamadır və daha dürüstdür. Növbə hər dövrədə yenidən qurulur.</p><p>Özü bitmir: tapşırıq siyahısındakı dayandır düyməsi ilə dayandırın.</p>",
    },
    "loop.go": {
        "ru": "Запустить круг", "en": "Start the loop", "tr": "Donguyu baslat",
        "kk": "Шеңберді бастау", "uz": "Aylanani boshlash", "az": "Dövrəni başlat",
    },
    "loop.nothing": {
        "ru": "Нечего качать: всё выбранное уже на диске.",
        "en": "Nothing to download: everything selected is already on disk.",
        "tr": "Indirilecek bir sey yok.", "kk": "Жүктейтін ештеңе жоқ.",
        "uz": "Yuklaydigan hech narsa yoʻq.", "az": "Endiriləcək heç nə yoxdur.",
    },
    "job.download-loop": {
        "ru": "выгрузка по кругу", "en": "download on repeat",
        "tr": "dongusel indirme", "kk": "шеңберлі жүктеу",
        "uz": "aylanma yuklash", "az": "dövrəli endirmə",
    },
    "btn.download": {
        "ru": "Скачать выбранное", "en": "Download selected", "tr": "Seçilenleri indir",
        "kk": "Таңдалғанды жүктеу", "uz": "Tanlanganni yuklash", "az": "Seçilmişləri endir",
    },
    "btn.download.title": {
        "ru": "Выгрузить выбранное в локальное зеркало",
        "en": "Download the selection into the local mirror",
        "tr": "Seçimi yerel aynaya indir",
        "kk": "Таңдалғанды жергілікті айнаға жүктеу",
        "uz": "Tanlanganni mahalliy nusxaga yuklash",
        "az": "Seçimi yerli güzgüyə endir",
    },
    "salvage.title": {
        "ru": "Читать блоками и пропускать мёртвые участки: файл выйдет с дырками, но часть содержимого спасётся",
        "en": "Read in blocks and skip dead ranges: the file will have gaps, but part of the content is saved",
        "tr": "Bloklar hâlinde oku ve ölü aralıkları atla: dosyada boşluk olur ama içeriğin bir kısmı kurtulur",
        "kk": "Блоктармен оқып, өлі бөліктерді аттап өту: файлда олқылық болады, бірақ мазмұнның бір бөлігі құтқарылады",
        "uz": "Bloklar bilan oʻqish va oʻlik qismlarni oʻtkazib yuborish: faylda boʻshliq boʻladi, lekin mazmunning bir qismi saqlanadi",
        "az": "Bloklarla oxu və ölü hissələri ötür: faylda boşluq olacaq, amma məzmunun bir hissəsi xilas olacaq",
    },
    "btn.archives": {
        "ru": "Архивы…", "en": "Archives…", "tr": "Arşivler…",
        "kk": "Мұрағаттар…", "uz": "Arxivlar…", "az": "Arxivlər…",
    },
    "btn.archives.title": {
        "ru": "Список архивов, проверка томов, освобождение места",
        "en": "Archive list, volume verification, freeing space",
        "tr": "Arşiv listesi, birim doğrulama, yer açma",
        "kk": "Мұрағаттар тізімі, томдарды тексеру, орын босату",
        "uz": "Arxivlar roʻyxati, jildlarni tekshirish, joy boʻshatish",
        "az": "Arxiv siyahısı, cildlərin yoxlanması, yer azad etmə",
    },
    "btn.log": {
        "ru": "Лог…", "en": "Log…", "tr": "Günlük…",
        "kk": "Журнал…", "uz": "Jurnal…", "az": "Jurnal…",
    },
    "btn.log.title": {
        "ru": "Подробный лог: что именно произошло и почему упало",
        "en": "Detailed log: what exactly happened and why it failed",
        "tr": "Ayrıntılı günlük: tam olarak ne oldu ve neden başarısız oldu",
        "kk": "Толық журнал: нақты не болды және неге құлады",
        "uz": "Batafsil jurnal: aniq nima boʻldi va nega yiqildi",
        "az": "Ətraflı jurnal: dəqiq nə baş verdi və niyə uğursuz oldu",
    },
    "btn.auth": {
        "ru": "Доступ…", "en": "Access…", "tr": "Erişim…",
        "kk": "Қатынау…", "uz": "Kirish…", "az": "Giriş…",
    },
    "btn.auth.title": {
        "ru": "ClientID, Client secret и токен Яндекс.Диска",
        "en": "ClientID, Client secret and the Yandex.Disk token",
        "tr": "ClientID, Client secret ve Yandex.Disk tokenı",
        "kk": "ClientID, Client secret және Yandex.Disk токені",
        "uz": "ClientID, Client secret va Yandex.Disk tokeni",
        "az": "ClientID, Client secret və Yandex.Disk tokeni",
    },
    "btn.clear": {
        "ru": "Снять выбор", "en": "Clear selection", "tr": "Seçimi temizle",
        "kk": "Таңдауды алу", "uz": "Tanlovni bekor qilish", "az": "Seçimi təmizlə",
    },
    "btn.cancel": {
        "ru": "Отмена", "en": "Cancel", "tr": "İptal",
        "kk": "Болдырмау", "uz": "Bekor qilish", "az": "Ləğv et",
    },
    "btn.close": {
        "ru": "Закрыть", "en": "Close", "tr": "Kapat",
        "kk": "Жабу", "uz": "Yopish", "az": "Bağla",
    },
    "btn.stopping": {
        "ru": "останавливаю…", "en": "stopping…", "tr": "durduruluyor…",
        "kk": "тоқтатылуда…", "uz": "toʻxtatilmoqda…", "az": "dayandırılır…",
    },
    "btn.stop": {
        "ru": "стоп", "en": "stop", "tr": "dur",
        "kk": "тоқтату", "uz": "toʻxtatish", "az": "dayandır",
    },

    # ── панель выбора ────────────────────────────────────────────────
    "sel.none": {
        "ru": "Ничего не выбрано", "en": "Nothing selected", "tr": "Hiçbir şey seçilmedi",
        "kk": "Ештеңе таңдалмаған", "uz": "Hech narsa tanlanmagan", "az": "Heç nə seçilməyib",
    },
    "sel.counting": {
        "ru": "считаю…", "en": "counting…", "tr": "hesaplanıyor…",
        "kk": "есептеп жатыр…", "uz": "hisoblanmoqda…", "az": "hesablanır…",
    },
    "sel.total": {
        "ru": "Выбрано <b>{count}</b> {files} · <b>{size}</b>",
        "en": "Selected <b>{count}</b> {files} · <b>{size}</b>",
        "tr": "Seçilen <b>{count}</b> {files} · <b>{size}</b>",
        "kk": "Таңдалды <b>{count}</b> {files} · <b>{size}</b>",
        "uz": "Tanlandi <b>{count}</b> {files} · <b>{size}</b>",
        "az": "Seçildi <b>{count}</b> {files} · <b>{size}</b>",
    },
    "sel.p.avail": {
        "ru": "<b>{n}</b> к выгрузке ({size})", "en": "<b>{n}</b> to download ({size})",
        "tr": "<b>{n}</b> indirilecek ({size})", "kk": "<b>{n}</b> жүктеуге ({size})",
        "uz": "<b>{n}</b> yuklashga ({size})", "az": "<b>{n}</b> endiriləcək ({size})",
    },
    "sel.p.saved": {
        "ru": "уже спасено {n}", "en": "already rescued {n}",
        "tr": "zaten kurtarılmış {n}", "kk": "құтқарылған {n}",
        "uz": "allaqachon qutqarilgan {n}", "az": "artıq xilas edilmiş {n}",
    },
    "sel.p.unavail": {
        "ru": "недоступно {n}", "en": "unavailable {n}",
        "tr": "erişilemez {n}", "kk": "қолжетімсіз {n}",
        "uz": "mavjud emas {n}", "az": "əlçatmaz {n}",
    },
    "sel.p.unchecked": {
        "ru": "не проверено {n}", "en": "unchecked {n}",
        "tr": "denetlenmemiş {n}", "kk": "тексерілмеген {n}",
        "uz": "tekshirilmagan {n}", "az": "yoxlanılmamış {n}",
    },
    "sel.failed": {
        "ru": "не смог посчитать: {error}", "en": "could not count: {error}",
        "tr": "hesaplanamadı: {error}", "kk": "есептей алмадым: {error}",
        "uz": "hisoblab boʻlmadi: {error}", "az": "hesablaya bilmədim: {error}",
    },
    "filter.onlyAvailable": {
        "ru": "только доступные", "en": "available only", "tr": "yalnızca erişilebilir",
        "kk": "тек қолжетімді", "uz": "faqat mavjud", "az": "yalnız əlçatan",
    },
    "filter.onlyUnsaved": {
        "ru": "только неспасённые", "en": "not rescued only",
        "tr": "yalnızca kurtarılmamış", "kk": "тек құтқарылмаған",
        "uz": "faqat qutqarilmagan", "az": "yalnız xilas edilməmiş",
    },
    "search.ph": {
        "ru": "Поиск по имени файла…", "en": "Search by file name…",
        "tr": "Dosya adına göre ara…", "kk": "Файл атауы бойынша іздеу…",
        "uz": "Fayl nomi boʻyicha qidirish…", "az": "Fayl adına görə axtar…",
    },
    "search.empty": {
        "ru": "Ничего не найдено.", "en": "Nothing found.", "tr": "Hiçbir şey bulunamadı.",
        "kk": "Ештеңе табылмады.", "uz": "Hech narsa topilmadi.", "az": "Heç nə tapılmadı.",
    },

    # ── дерево ───────────────────────────────────────────────────────
    "tree.empty": {
        "ru": "Опись пуста. Нажми «Опись облака» — это первое, что стоит сделать: имена, размеры, хеши и превью спасаются даже у файлов, содержимое которых уже не отдаётся.",
        "en": "The inventory is empty. Press “Inventory” — it is the first thing to do: names, sizes, hashes and previews are saved even for files whose content is no longer served.",
        "tr": "Envanter boş. “Envanter çıkar”a basın — yapılacak ilk şey budur: adlar, boyutlar, özetler ve önizlemeler, içeriği artık sunulmayan dosyalar için bile kurtarılır.",
        "kk": "Тізім бос. «Тізімдеу» батырмасын басыңыз — бұл алдымен істеу керек нәрсе: атаулар, өлшемдер, хэштер мен нобайлар мазмұны берілмейтін файлдар үшін де сақталады.",
        "uz": "Roʻyxat boʻsh. “Roʻyxatga olish” tugmasini bosing — bu birinchi qilinadigan ish: nomlar, oʻlchamlar, xeshlar va koʻrinishlar mazmuni berilmaydigan fayllar uchun ham saqlanadi.",
        "az": "Siyahı boşdur. “Siyahıya al” düyməsini basın — ilk görüləcək iş budur: adlar, ölçülər, heşlər və önizləmələr məzmunu artıq verilməyən fayllar üçün də saxlanılır.",
    },
    "tree.dirTip": {
        "ru": "доступно {ok}, недоступно {bad}, не проверено {unchecked}",
        "en": "available {ok}, unavailable {bad}, unchecked {unchecked}",
        "tr": "erişilebilir {ok}, erişilemez {bad}, denetlenmemiş {unchecked}",
        "kk": "қолжетімді {ok}, қолжетімсіз {bad}, тексерілмеген {unchecked}",
        "uz": "mavjud {ok}, mavjud emas {bad}, tekshirilmagan {unchecked}",
        "az": "əlçatan {ok}, əlçatmaz {bad}, yoxlanılmamış {unchecked}",
    },
    "tree.fileTip": {
        "ru": "состояние: {state}", "en": "state: {state}", "tr": "durum: {state}",
        "kk": "күйі: {state}", "uz": "holati: {state}", "az": "vəziyyət: {state}",
    },
    "badge.saved": {
        "ru": "спасено {n}", "en": "rescued {n}", "tr": "kurtarıldı {n}",
        "kk": "құтқарылды {n}", "uz": "qutqarildi {n}", "az": "xilas edildi {n}",
    },
    "badge.savedOne": {
        "ru": "спасён", "en": "rescued", "tr": "kurtarıldı",
        "kk": "құтқарылды", "uz": "qutqarildi", "az": "xilas edildi",
    },
    "badge.archivedN": {
        "ru": "в архиве {n}", "en": "archived {n}", "tr": "arşivde {n}",
        "kk": "мұрағатта {n}", "uz": "arxivda {n}", "az": "arxivdə {n}",
    },
    "badge.archived": {
        "ru": "в архиве", "en": "archived", "tr": "arşivde",
        "kk": "мұрағатта", "uz": "arxivda", "az": "arxivdə",
    },
    "badge.removedN": {
        "ru": "убрано {n}", "en": "removed {n}", "tr": "kaldırıldı {n}",
        "kk": "алынды {n}", "uz": "olib tashlandi {n}", "az": "silindi {n}",
    },
    "badge.gaps": {
        "ru": "с дырками", "en": "with gaps", "tr": "boşluklu",
        "kk": "олқылықпен", "uz": "boʻshliqlar bilan", "az": "boşluqlarla",
    },
    "badge.released": {
        "ru": "место убрано", "en": "space freed", "tr": "yer açıldı",
        "kk": "орын босатылды", "uz": "joy boʻshatildi", "az": "yer azad edildi",
    },
    "badge.notInCloud": {
        "ru": "нет в облаке", "en": "not in cloud", "tr": "bulutta yok",
        "kk": "бұлтта жоқ", "uz": "bulutda yoʻq", "az": "buludda yoxdur",
    },
    "badge.preview": {
        "ru": "превью", "en": "preview", "tr": "önizleme",
        "kk": "нобай", "uz": "koʻrinish", "az": "önizləmə",
    },

    # ── подробности файла ────────────────────────────────────────────
    "detail.empty": {
        "ru": "Выбери файл, чтобы увидеть, что о нём известно.",
        "en": "Pick a file to see what is known about it.",
        "tr": "Hakkında ne bilindiğini görmek için bir dosya seçin.",
        "kk": "Файл туралы не білетінін көру үшін оны таңдаңыз.",
        "uz": "Fayl haqida nima maʼlum ekanini koʻrish uchun uni tanlang.",
        "az": "Fayl haqqında nə bilindiyini görmək üçün onu seçin.",
    },
    "detail.path": {"ru": "путь", "en": "path", "tr": "yol", "kk": "жол", "uz": "yoʻl", "az": "yol"},
    "detail.size": {"ru": "размер", "en": "size", "tr": "boyut", "kk": "өлшемі", "uz": "oʻlcham", "az": "ölçü"},
    "detail.type": {"ru": "тип", "en": "type", "tr": "tür", "kk": "түрі", "uz": "turi", "az": "növ"},
    "detail.modified": {"ru": "изменён", "en": "modified", "tr": "değiştirilme", "kk": "өзгертілген", "uz": "oʻzgartirilgan", "az": "dəyişdirilib"},
    "detail.availability": {"ru": "доступность", "en": "availability", "tr": "erişilebilirlik", "kk": "қолжетімділік", "uz": "mavjudlik", "az": "əlçatanlıq"},
    "detail.serverResponse": {"ru": "ответ сервера", "en": "server response", "tr": "sunucu yanıtı", "kk": "сервер жауабы", "uz": "server javobi", "az": "server cavabı"},
    "detail.storageHost": {"ru": "машина хранилища", "en": "storage host", "tr": "depolama sunucusu", "kk": "қойма машинасы", "uz": "ombor mashinasi", "az": "anbar maşını"},
    "detail.checked": {"ru": "проверен", "en": "checked", "tr": "denetlendi", "kk": "тексерілген", "uz": "tekshirilgan", "az": "yoxlanılıb"},
    "detail.attempts": {"ru": "{s} (попыток {n})", "en": "{s} ({n} attempts)", "tr": "{s} ({n} deneme)", "kk": "{s} ({n} әрекет)", "uz": "{s} ({n} urinish)", "az": "{s} ({n} cəhd)"},
    "detail.md5": {"ru": "md5 в облаке", "en": "md5 in cloud", "tr": "bulutta md5", "kk": "бұлттағы md5", "uz": "bulutdagi md5", "az": "buluddakı md5"},
    "detail.sha256": {"ru": "sha256 в облаке", "en": "sha256 in cloud", "tr": "bulutta sha256", "kk": "бұлттағы sha256", "uz": "bulutdagi sha256", "az": "buluddakı sha256"},
    "detail.rescued": {"ru": "спасён", "en": "rescued", "tr": "kurtarıldı", "kk": "құтқарылды", "uz": "qutqarildi", "az": "xilas edildi"},
    "detail.holes": {"ru": "дырки", "en": "gaps", "tr": "boşluklar", "kk": "олқылықтар", "uz": "boʻshliqlar", "az": "boşluqlar"},
    "detail.previewState": {"ru": "превью", "en": "preview", "tr": "önizleme", "kk": "нобай", "uz": "koʻrinish", "az": "önizləmə"},
    "detail.spaceFreed": {"ru": ", место убрано", "en": ", space freed", "tr": ", yer açıldı", "kk": ", орын босатылды", "uz": ", joy boʻshatildi", "az": ", yer azad edildi"},

    # ── работы ───────────────────────────────────────────────────────
    "job.scan": {"ru": "опись", "en": "inventory", "tr": "envanter", "kk": "тізімдеу", "uz": "roʻyxat", "az": "siyahı"},
    "job.previews": {"ru": "превью", "en": "previews", "tr": "önizlemeler", "kk": "нобайлар", "uz": "koʻrinishlar", "az": "önizləmələr"},
    "job.probe": {"ru": "проверка", "en": "check", "tr": "denetim", "kk": "тексеру", "uz": "tekshiruv", "az": "yoxlama"},
    "job.download": {"ru": "выгрузка", "en": "download", "tr": "indirme", "kk": "жүктеу", "uz": "yuklash", "az": "endirmə"},
    "job.archive": {"ru": "архивация", "en": "archiving", "tr": "arşivleme", "kk": "мұрағаттау", "uz": "arxivlash", "az": "arxivləşdirmə"},
    "job.cloud-delete": {"ru": "удаление из облака", "en": "cloud deletion", "tr": "buluttan silme", "kk": "бұлттан жою", "uz": "bulutdan oʻchirish", "az": "buluddan silmə"},
    "job.state.running": {"ru": "идёт", "en": "running", "tr": "çalışıyor", "kk": "орындалуда", "uz": "bajarilmoqda", "az": "icra olunur"},
    "job.state.done": {"ru": "готово", "en": "done", "tr": "tamam", "kk": "дайын", "uz": "tayyor", "az": "hazır"},
    "job.state.failed": {"ru": "ошибка", "en": "failed", "tr": "hata", "kk": "қате", "uz": "xato", "az": "xəta"},
    "autopilot.label": {
        "ru": "автопилот", "en": "autopilot", "tr": "otopilot",
        "kk": "автопилот", "uz": "avtopilot", "az": "avtopilot",
    },
    "autopilot.title": {
        "ru": "Каждые пару часов перепроверять недоступные файлы и сразу качать те, что ожили. Доступность меняется быстрее, чем идёт полный проход пробы.",
        "en": "Every couple of hours, re-check unavailable files and immediately download the ones that came back. Availability here changes faster than a full probe pass: on Oct 18, a fifth of the \"available\" files died within two hours, and 71 died between the probe and the download.",
        "tr": "İki saatte bir erişilemeyen dosyaları yeniden denetler ve gelenleri hemen indirir. Erişilebilirlik tam bir denetim turundan hızlı değişir: 18 Ekim'de \"erişilebilir\" dosyaların beşte biri iki saat içinde öldü, 71'i denetim ile indirme arasında.",
        "kk": "Екі сағат сайын қолжетімсіз файлдарды қайта тексеріп, тірілгенін бірден жүктейді. Қолжетімділік толық тексеруден жылдам өзгереді: 18 қазанда «қолжетімді» файлдардың бестен бірі екі сағатта өлді, 71-і тексеру мен жүктеу арасында.",
        "uz": "Ikki soatda bir ishlamaydigan fayllarni qayta tekshirib, tirilganini darhol yuklab oladi. Bu yerda qulaylik toʻliq tekshiruvdan tez oʻzgaradi: 18 oktyabrda «ishlaydigan» fayllarning beshtan biri ikki soatda oʻldi, 71-и tekshiruv bilan yuklab olish orasida.",
        "az": "İki saatda bir əlçatmaz faylları yenidən yoxlayır və dirilənləri dərhal endirir. Burada əlçatmazlıq tam yoxlamadan tez dəyişir: 18 oktyabrda «əlçatan» faylların beşdə biri iki saatda öldü, 71-i yoxlama ilə endirmə arasında.",
    },
    "autopilot.next": {
        "ru": "следующий круг автопилота: {n}", "en": "next autopilot round: {n}",
        "tr": "sonraki otopilot turu: {n}", "kk": "автопилоттың келекі туры: {n}",
        "uz": "keyingi avtopilot turi: {n}", "az": "növbəti avtopilot turu: {n}",
    },
    "autopilot.nextSoon": {
        "ru": "автопилот: первый круг скоро", "en": "autopilot: first round soon",
        "tr": "otopilot: ilk tur yakında", "kk": "автопилот: бірінші тур жақында",
        "uz": "avtopilot: birinchi tur tez orada", "az": "avtopilot: ilk tur tezliklə",
    },
    "chip.hosts": {
        "ru": "узлы хранения: живых {alive}, мёртвых {dead} (лучший {best}%)",
        "en": "storage nodes: {alive} alive, {dead} dead (best {best}%)",
        "tr": "depolama düğümleri: {alive} canlı, {dead} ölü (en iyi {best}%)",
        "kk": "сақтау түйіндері: {alive} тірі, {dead} өлі (ең жақсы {best}%)",
        "uz": "saqlash tugunlari: {alive} tirik, {dead} oʻlik (eng yaxshi {best}%)",
        "az": "saxlama qovşaqları: {alive} diri, {dead} ölü (ən yaxşı {best}%)",
    },
    "job.adopt": {
        "ru": "учёт перенесённого", "en": "adopt local files", "tr": "yerel dosyaları al",
        "kk": "жергілікті файлдарды есептеу", "uz": "mahalliy fayllarni hisobga olish",
        "az": "yerli faylları hesaba alma",
    },
    "job.mirror": {
        "ru": "сверка зеркала", "en": "mirror sync", "tr": "ayna eşitleme",
        "kk": "айна синхрондау", "uz": "oyna sinxronlash", "az": "ayna sinxronizasiya",
    },
    "job.autopilot": {
        "ru": "автопилот", "en": "autopilot", "tr": "otopilot",
        "kk": "автопилот", "uz": "avtopilot", "az": "avtopilot",
    },
    "job.state.cancelled": {"ru": "отменено", "en": "cancelled", "tr": "iptal edildi", "kk": "бас тартылды", "uz": "bekor qilindi", "az": "ləğv edildi"},
    "job.state.interrupted": {"ru": "прервано", "en": "interrupted", "tr": "kesildi", "kk": "үзілді", "uz": "uzildi", "az": "kəsildi"},
    "job.state.partial": {"ru": "готово с ошибками", "en": "done with errors", "tr": "hatalarla bitti", "kk": "қателермен бітті", "uz": "xatolar bilan tugadi", "az": "xətalarla bitdi"},

    # ── окно выгрузки ────────────────────────────────────────────────
    "dl.title": {"ru": "Выгрузка", "en": "Download", "tr": "İndirme", "kk": "Жүктеу", "uz": "Yuklash", "az": "Endirmə"},
    "dl.body": {
        "ru": "<p>К выгрузке <b>{avail}</b> {files}, <b>{availSize}</b> — включая непроверенные.</p><p>Уже спасено и будет пропущено: {already} ({alreadySize}).<br>Недоступно сейчас: {unavail}. Не проверено: {unchecked}.</p>",
        "en": "<p>To download: <b>{avail}</b> {files}, <b>{availSize}</b> — including unchecked.</p><p>Already rescued and will be skipped: {already} ({alreadySize}).<br>Currently unavailable: {unavail}. Unchecked: {unchecked}.</p>",
        "tr": "<p>İndirilecek: <b>{avail}</b> {files}, <b>{availSize}</b>.</p><p>Zaten kurtarılmış, atlanacak: {already} ({alreadySize}).<br>Şu anda erişilemez: {unavail}. Denetlenmemiş: {unchecked}.</p>",
        "kk": "<p>Жүктеуге: <b>{avail}</b> {files}, <b>{availSize}</b>.</p><p>Құтқарылған, аттап өтіледі: {already} ({alreadySize}).<br>Қазір қолжетімсіз: {unavail}. Тексерілмеген: {unchecked}.</p>",
        "uz": "<p>Yuklashga: <b>{avail}</b> {files}, <b>{availSize}</b>.</p><p>Allaqachon qutqarilgan, oʻtkazib yuboriladi: {already} ({alreadySize}).<br>Hozir mavjud emas: {unavail}. Tekshirilmagan: {unchecked}.</p>",
        "az": "<p>Endirmək üçün: <b>{avail}</b> {files}, <b>{availSize}</b>.</p><p>Artıq xilas edilib, ötürüləcək: {already} ({alreadySize}).<br>Hazırda əlçatmaz: {unavail}. Yoxlanılmamış: {unchecked}.</p>",
    },
    "dl.salvageWarn": {
        "ru": "salvage-режим: файлы читаются блоками, мёртвые участки пропускаются. Такие файлы помечаются «с дырками» и НИКОГДА не предлагаются к удалению из облака.",
        "en": "salvage mode: files are read in blocks, dead ranges are skipped. Such files are marked “with gaps” and are NEVER offered for deletion from the cloud.",
        "tr": "salvage kipi: dosyalar bloklar hâlinde okunur, ölü aralıklar atlanır. Bu dosyalar “boşluklu” işaretlenir ve buluttan silinmek üzere ASLA önerilmez.",
        "kk": "salvage режимі: файлдар блоктармен оқылады, өлі бөліктер аттап өтіледі. Мұндай файлдар «олқылықпен» деп белгіленеді және бұлттан жоюға ЕШҚАШАН ұсынылмайды.",
        "uz": "salvage rejimi: fayllar bloklar bilan oʻqiladi, oʻlik qismlar oʻtkazib yuboriladi. Bunday fayllar “boʻshliqlar bilan” deb belgilanadi va bulutdan oʻchirishga HECH QACHON taklif qilinmaydi.",
        "az": "salvage rejimi: fayllar bloklarla oxunur, ölü hissələr ötürülür. Belə fayllar “boşluqlarla” işarələnir və buluddan silinmək üçün HEÇ VAXT təklif olunmur.",
    },
    "dl.note": {
        "ru": "<p>Структура папок повторяется один в один. Хеши сверяются с теми, что сообщил Яндекс.</p>",
        "en": "<p>The folder structure is mirrored exactly. Hashes are verified against those reported by Yandex.</p>",
        "tr": "<p>Klasör yapısı birebir yansıtılır. Özetler Yandex'in bildirdikleriyle doğrulanır.</p>",
        "kk": "<p>Қалталар құрылымы дәл қайталанады. Хэштер Яндекс хабарлағанмен салыстырылады.</p>",
        "uz": "<p>Papkalar tuzilmasi aynan takrorlanadi. Xeshlar Yandeks bildirganlari bilan solishtiriladi.</p>",
        "az": "<p>Qovluq strukturu eyni ilə təkrarlanır. Heşlər Yandeksin bildirdikləri ilə yoxlanılır.</p>",
    },
    "dl.go": {
        "ru": "Качать {n} шт", "en": "Download {n}", "tr": "{n} tanesini indir",
        "kk": "{n} дана жүктеу", "uz": "{n} dona yuklash", "az": "{n} ədəd endir",
    },
    "probe.nothing": {
        "ru": "Нечего проверять по этим условиям.", "en": "Nothing to check under these conditions.",
        "tr": "Bu koşullarda denetlenecek bir şey yok.", "kk": "Бұл шарттар бойынша тексеретін ештеңе жоқ.",
        "uz": "Bu shartlar boʻyicha tekshiradigan hech narsa yoʻq.", "az": "Bu şərtlərlə yoxlanılacaq heç nə yoxdur.",
    },

    # ── архивы ───────────────────────────────────────────────────────
    "arch.started": {
        "ru": "Упаковка запущена: {n} файлов, {size}.\nОригиналы останутся на месте — удалить их можно через «Архивы…» после того, как тома уедут в Телеграм.",
        "en": "Packing started: {n} files, {size}.\nOriginals stay in place — you can remove them via “Archives…” once the volumes are in Telegram.",
        "tr": "Paketleme başladı: {n} dosya, {size}.\nOrijinaller yerinde kalır — birimler Telegram'a gittikten sonra “Arşivler…” ile silebilirsiniz.",
        "kk": "Буу басталды: {n} файл, {size}.\nТүпнұсқалар орнында қалады — томдар Телеграмға кеткен соң «Мұрағаттар…» арқылы жоюға болады.",
        "uz": "Qadoqlash boshlandi: {n} fayl, {size}.\nAsl nusxalar joyida qoladi — jildlar Telegramga ketgach “Arxivlar…” orqali oʻchirish mumkin.",
        "az": "Yığma başladı: {n} fayl, {size}.\nOrijinallar yerində qalır — cildlər Teleqrama getdikdən sonra “Arxivlər…” vasitəsilə silə bilərsiniz.",
    },
    "arch.scope.title": {
        "ru": "Что паковать: всё готовое или только отмеченное в дереве",
        "en": "What to pack: everything ready, or only what is ticked in the tree",
        "tr": "Ne paketlenecek: hazir olan her sey ya da agacta isaretlenenler",
        "kk": "Нені буу: дайынның бәрі немесе ағашта белгіленгені",
        "uz": "Nimani qadoqlash: tayyor hammasi yoki daraxtda belgilangani",
        "az": "Nə yığmalı: hazır olan hər şey və ya ağacda işarələnənlər",
    },
    "arch.volume.title": {
        "ru": "Размер тома. 3900 МБ -- предел Телеграм-премиум, 1900 МБ -- обычного",
        "en": "Volume size. 3900 MB is the Telegram Premium limit, 1900 MB the regular one",
        "tr": "Birim boyutu. 3900 MB Telegram Premium siniri, 1900 MB normal",
        "kk": "Том өлшемі. 3900 МБ -- Телеграм-премиум шегі, 1900 МБ -- әдеттегі",
        "uz": "Jild oʻlchami. 3900 MB -- Telegram Premium chegarasi, 1900 MB -- oddiy",
        "az": "Cild ölçüsü. 3900 MB Teleqram Premium həddi, 1900 MB adi",
    },
    "arch.plan": {
        "ru": "<p>К упаковке <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "en": "<p>To pack: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "tr": "<p>Paketlenecek: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "kk": "<p>Буылады: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "uz": "<p>Qadoqlanadi: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "az": "<p>Yığılacaq: <b>{n}</b> {files}, <b>{size}</b>.</p>",
    },
    "arch.plan.volumes": {
        "ru": "<p>Томов по {vol}: примерно <b>{k}</b>.</p>",
        "en": "<p>Volumes of {vol}: about <b>{k}</b>.</p>",
        "tr": "<p>{vol} birim: yaklasik <b>{k}</b>.</p>",
        "kk": "<p>{vol} томдары: шамамен <b>{k}</b>.</p>",
        "uz": "<p>{vol} jildlari: taxminan <b>{k}</b>.</p>",
        "az": "<p>{vol} cildləri: təxminən <b>{k}</b>.</p>",
    },
    "arch.plan.whole": {
        "ru": "<p>Выбрано «всё готовое»: это вся спасённая коллекция, паковка может идти часами. Отметь папку в дереве и выбери «только отмеченное», если нужна часть.</p>",
        "en": "<p>“Everything ready” means the whole rescued collection; packing can take hours. Tick a folder in the tree and choose “only ticked” for a part.</p>",
        "tr": "<p>“Hazir olan her sey” tum kurtarilan koleksiyondur; paketleme saatler surebilir. Bir klasoru isaretleyip “yalnizca isaretlenenler”i secin.</p>",
        "kk": "<p>«Дайынның бәрі» -- бұл бүкіл құтқарылған жинақ, буу сағаттарға созылуы мүмкін. Бөлігі керек болса, ағашта қалтаны белгілеңіз.</p>",
        "uz": "<p>“Tayyor hammasi” -- bu butun qutqarilgan toʻplam, qadoqlash soatlab davom etishi mumkin. Qismi kerak boʻlsa, daraxtda papkani belgilang.</p>",
        "az": "<p>“Hazır olan hər şey” bütün xilas edilmiş kolleksiyadır; yığma saatlarla çəkə bilər. Hissəsi lazımdırsa, ağacda qovluğu işarələyin.</p>",
    },
    "arch.go": {
        "ru": "Паковать {n}", "en": "Pack {n}", "tr": "{n} paketle",
        "kk": "{n} буу", "uz": "{n} qadoqlash", "az": "{n} yığ",
    },
    "arch.nothing": {
        "ru": "Паковать нечего: нет проверенных файлов вне архивов.",
        "en": "Nothing to pack: no verified files outside archives.",
        "tr": "Paketlenecek bir sey yok.", "kk": "Буатын ештеңе жоқ.",
        "uz": "Qadoqlaydigan hech narsa yoʻq.", "az": "Yığılacaq heç nə yoxdur.",
    },
    "arch.title": {"ru": "Архивы", "en": "Archives", "tr": "Arşivler", "kk": "Мұрағаттар", "uz": "Arxivlar", "az": "Arxivlər"},
    "arch.none": {"ru": "Архивов пока нет.", "en": "No archives yet.", "tr": "Henüz arşiv yok.", "kk": "Әзірге мұрағат жоқ.", "uz": "Hozircha arxiv yoʻq.", "az": "Hələ arxiv yoxdur."},
    "arch.col.name": {"ru": "имя", "en": "name", "tr": "ad", "kk": "атауы", "uz": "nomi", "az": "ad"},
    "arch.col.state": {"ru": "состояние", "en": "state", "tr": "durum", "kk": "күйі", "uz": "holati", "az": "vəziyyət"},
    "arch.col.files": {"ru": "файлов", "en": "files", "tr": "dosya", "kk": "файл", "uz": "fayl", "az": "fayl"},
    "arch.col.size": {"ru": "объём", "en": "size", "tr": "boyut", "kk": "көлемі", "uz": "hajmi", "az": "həcm"},
    "arch.col.volumes": {"ru": "томов", "en": "volumes", "tr": "birim", "kk": "том", "uz": "jild", "az": "cild"},
    "arch.verify": {"ru": "проверить", "en": "verify", "tr": "doğrula", "kk": "тексеру", "uz": "tekshirish", "az": "yoxla"},
    "arch.release": {"ru": "убрать оригиналы", "en": "remove originals", "tr": "orijinalleri sil", "kk": "түпнұсқаларды алу", "uz": "asl nusxalarni olib tashlash", "az": "orijinalları sil"},
    "arch.note": {
        "ru": "sha256 каждого тома записан — «проверить» пересчитает их и скажет, вернулся ли том из Телеграма целым. «Убрать оригиналы» удаляет локальные копии только после успешной проверки.",
        "en": "The sha256 of every volume is recorded — “verify” recomputes them and tells whether a volume came back from Telegram intact. “Remove originals” deletes local copies only after a successful check.",
        "tr": "Her birimin sha256'sı kayıtlı — “doğrula” bunları yeniden hesaplar ve birimin Telegram'dan sağlam dönüp dönmediğini söyler. “Orijinalleri sil” yerel kopyaları yalnızca başarılı doğrulamadan sonra siler.",
        "kk": "Әр томның sha256-і жазылған — «тексеру» оларды қайта есептеп, том Телеграмнан бүтін оралғанын айтады. «Түпнұсқаларды алу» жергілікті көшірмелерді тек сәтті тексеруден кейін жояды.",
        "uz": "Har bir jildning sha256 yozilgan — “tekshirish” ularni qayta hisoblab, jild Telegramdan butun qaytganini aytadi. “Asl nusxalarni olib tashlash” mahalliy nusxalarni faqat muvaffaqiyatli tekshiruvdan keyin oʻchiradi.",
        "az": "Hər cildin sha256-sı yazılıb — “yoxla” onları yenidən hesablayıb cildin Teleqramdan bütöv qayıtdığını deyir. “Orijinalları sil” yerli nüsxələri yalnız uğurlu yoxlamadan sonra silir.",
    },
    "arch.verifyResult": {
        "ru": "Тома: целых {ok}, битых {bad}, отсутствует {missing}",
        "en": "Volumes: intact {ok}, corrupt {bad}, missing {missing}",
        "tr": "Birimler: sağlam {ok}, bozuk {bad}, eksik {missing}",
        "kk": "Томдар: бүтін {ok}, бүлінген {bad}, жоқ {missing}",
        "uz": "Jildlar: butun {ok}, buzilgan {bad}, yoʻq {missing}",
        "az": "Cildlər: bütöv {ok}, zədəli {bad}, yoxdur {missing}",
    },
    "arch.corrupt": {"ru": "Битые: {list}", "en": "Corrupt: {list}", "tr": "Bozuk: {list}", "kk": "Бүлінген: {list}", "uz": "Buzilgan: {list}", "az": "Zədəli: {list}"},
    "arch.releaseConfirm": {
        "ru": "Удалить локальные оригиналы файлов этого архива?\nТома должны быть уже сохранены в Телеграм.",
        "en": "Delete the local originals of this archive's files?\nThe volumes should already be saved to Telegram.",
        "tr": "Bu arşivdeki dosyaların yerel orijinalleri silinsin mi?\nBirimler Telegram'a kaydedilmiş olmalı.",
        "kk": "Осы мұрағат файлдарының жергілікті түпнұсқаларын жою керек пе?\nТомдар Телеграмға сақталған болуы керек.",
        "uz": "Ushbu arxiv fayllarining mahalliy asl nusxalari oʻchirilsinmi?\nJildlar Telegramga saqlangan boʻlishi kerak.",
        "az": "Bu arxivin fayllarının yerli orijinalları silinsin?\nCildlər Teleqrama saxlanmış olmalıdır.",
    },
    "arch.released": {
        "ru": "Убрано {n} {files}, освобождено {size}",
        "en": "Removed {n} {files}, freed {size}",
        "tr": "{n} {files} kaldırıldı, {size} yer açıldı",
        "kk": "{n} {files} алынды, {size} босатылды",
        "uz": "{n} {files} olib tashlandi, {size} boʻshatildi",
        "az": "{n} {files} silindi, {size} azad edildi",
    },

    # ── удаление из облака ───────────────────────────────────────────
    "del.level.title": {
        "ru": "Насколько надёжно должно быть спасено, чтобы удалять из облака",
        "en": "How safely rescued a file must be before cloud deletion",
        "tr": "Buluttan silmeden önce dosyanın ne kadar güvenle kurtarılmış olması gerektiği",
        "kk": "Бұлттан жою үшін файл қаншалықты сенімді құтқарылуы керек",
        "uz": "Bulutdan oʻchirish uchun fayl qanchalik ishonchli qutqarilgan boʻlishi kerak",
        "az": "Buluddan silmək üçün faylın nə qədər etibarlı xilas edilməsi lazımdır",
    },
    "del.level.archived": {
        "ru": "в проверенном архиве", "en": "in a verified archive",
        "tr": "doğrulanmış arşivde", "kk": "тексерілген мұрағатта",
        "uz": "tekshirilgan arxivda", "az": "yoxlanılmış arxivdə",
    },
    "del.level.downloaded": {
        "ru": "скачано и хеш сошёлся", "en": "downloaded, hash matched",
        "tr": "indirildi, özet tuttu", "kk": "жүктелді, хэш сәйкес",
        "uz": "yuklandi, xesh mos keldi", "az": "endirildi, heş uyğun gəldi",
    },
    "del.level.junk": {
        "ru": "недоступный мусор (не спасён)", "en": "unavailable junk (not saved)",
        "tr": "erişilemez çöp (kurtarılmadı)", "kk": "қолжетімсіз қоқыс (сақталмаған)",
        "uz": "ochib boʻlmaydigan axlat (saqlanmagan)", "az": "əlçatmaz zibil (xilas olunmayıb)",
    },
    "del.junkWarn": {
        "ru": "<b>Это удаление мусора, а не спасения.</b> Сюда попадают только файлы, которые проба уже признала недоступными и которых у тебя нет ни на диске, ни в архиве. Удаляя их, ты освобождаешь квоту, но вернуть их будет нечем — даже если ЦОД оживут. Всё доступное и всё непроверенное сюда не входит намеренно.",
        "en": "<b>This deletes junk, not rescued data.</b> Only files the probe already found unavailable and that you have neither on disk nor in an archive are included. Deleting them frees quota, but there is no way to bring them back — even if the datacenters come alive. Everything available and everything unchecked is excluded on purpose.",
        "tr": "<b>Bu çöp silme, kurtarma değil.</b> Yalnızca denetimin erişilemez bulduğu ve diskte ya da arşivde olmayan dosyalar girer. Silmek kotayı boşaltır ama geri getirmenin yolu yok — veri merkezleri canlansa bile. Erişilebilir ve denetlenmemiş her şey kasten dışarıda.",
        "kk": "<b>Бұл қоқысты жою, құтқару емес.</b> Тексеру қолжетімсіз деп тапқан және дискіде не мұрағатта жоқ файлдар ғана кіреді. Оларды жою квотаны босатады, бірақ қайтару жолы жоқ — ЦОД тірілсе де. Қолжетімді және тексерілмегеннің бәрі әдейі кірмейді.",
        "uz": "<b>Bu axlatni oʻchirish, qutqarish emas.</b> Faqat tekshiruv ochib boʻlmaydi deb topgan va diskda ham, arxivda ham yoʻq fayllar kiradi. Ularni oʻchirish kvotani boʻshatadi, lekin qaytarishning yoʻli yoʻq — maʼlumot markazlari jonlansa ham. Ochiladigan va tekshirilmagan hamma narsa ataylab kirmaydi.",
        "az": "<b>Bu zibil silməkdir, xilas etmək deyil.</b> Yalnız yoxlama əlçatmaz hesab etdiyi və diskdə ya arxivdə olmayan fayllar daxildir. Onları silmək kvotanı boşaldır, amma geri qaytarmağın yolu yoxdur — məlumat mərkəzləri dirilsə belə. Əlçatan və yoxlanılmamış hər şey qəsdən kənardadır.",
    },
    "del.junkConfirm": {
        "ru": "Удалить из облака {n} {files} мусора НАВСЕГДА? Восстановить их будет нельзя.",
        "en": "Delete {n} {files} of junk from the cloud FOREVER? They cannot be restored.",
        "tr": "{n} {files} çöpü buluttan SONSUZA DEK silinsin mi? Geri getirilemez.",
        "kk": "Бұлттан {n} {files} қоқысты МӘҢГІЛІК жою керек пе? Қалпына келтіру мүмкін емес.",
        "uz": "Bulutdan {n} {files} axlatni ABADIY oʻchirilsinmi? Qaytarib boʻlmaydi.",
        "az": "Bulutdan {n} {files} zibili ƏBƏDİ silinsin? Bərpa etmək mümkün olmayacaq.",
    },
    "del.oneCopy": {
        "ru": "<b>Копия будет одна.</b> Файл есть только на этом диске: архива в Телеграме нет. Отказ диска — и файла не станет нигде. Для второго носителя сначала «Архивировать» и унеси тома.",
        "en": "<b>There will be one copy.</b> The file exists only on this disk: no archive in Telegram. A disk failure and it is gone everywhere. For a second medium, run “Archive” first and take the volumes away.",
        "tr": "<b>Tek kopya kalacak.</b> Dosya yalnızca bu diskte: Telegram'da arşiv yok. Disk arızalanırsa hiçbir yerde kalmaz. İkinci bir ortam için önce “Arşivle” deyip birimleri götürün.",
        "kk": "<b>Көшірме біреу болады.</b> Файл тек осы дискіде: Телеграмда мұрағат жоқ. Диск істен шықса, файл еш жерде қалмайды. Екінші тасымалдағыш үшін алдымен «Мұрағаттау» жасап, томдарды алып кетіңіз.",
        "uz": "<b>Nusxa bitta boʻladi.</b> Fayl faqat shu diskda: Telegramda arxiv yoʻq. Disk ishdan chiqsa, fayl hech qayerda qolmaydi. Ikkinchi tashuvchi uchun avval “Arxivlash” qiling va jildlarni olib keting.",
        "az": "<b>Bir nüsxə qalacaq.</b> Fayl yalnız bu diskdədir: Teleqramda arxiv yoxdur. Disk sıradan çıxsa, fayl heç yerdə qalmayacaq. İkinci daşıyıcı üçün əvvəlcə “Arxivləşdir” edin və cildləri aparın.",
    },
    "del.title": {"ru": "Удаление из облака", "en": "Deleting from the cloud", "tr": "Buluttan silme", "kk": "Бұлттан жою", "uz": "Bulutdan oʻchirish", "az": "Buluddan silmə"},
    "del.warn": {
        "ru": "<b>Это необратимо.</b> Удаление идёт с <code>permanently=true</code>, минуя Корзину: файлы в Корзине ещё 30 дней занимают место в квоте, а смысл удаления — освободить место. Восстановить их после этого нельзя.",
        "en": "<b>This is irreversible.</b> Deletion uses <code>permanently=true</code>, bypassing the Trash: files in the Trash keep occupying quota for 30 days, and the point of deleting is to free space. They cannot be restored afterwards.",
        "tr": "<b>Bu geri alınamaz.</b> Silme <code>permanently=true</code> ile, Çöp Kutusu atlanarak yapılır: Çöp Kutusundaki dosyalar 30 gün daha kotadan yer kaplar, silmenin amacı ise yer açmaktır. Sonrasında geri getirilemezler.",
        "kk": "<b>Бұл қайтымсыз.</b> Жою <code>permanently=true</code> арқылы, Себетті айналып өтеді: Себеттегі файлдар тағы 30 күн квотадан орын алады, ал жоюдың мәні — орын босату. Содан кейін оларды қалпына келтіру мүмкін емес.",
        "uz": "<b>Bu qaytarib boʻlmaydi.</b> Oʻchirish <code>permanently=true</code> bilan, Savatni chetlab oʻtadi: Savatdagi fayllar yana 30 kun kvotadan joy egallaydi, oʻchirishning maʼnosi esa joy boʻshatish. Undan keyin ularni tiklab boʻlmaydi.",
        "az": "<b>Bu geri qaytarılmazdır.</b> Silmə <code>permanently=true</code> ilə, Səbəti keçərək aparılır: Səbətdəki fayllar daha 30 gün kvotadan yer tutur, silmənin mənası isə yer azad etməkdir. Sonra onları bərpa etmək mümkün deyil.",
    },
    "del.fits": {
        "ru": "<p>Подходит к удалению: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "en": "<p>Eligible for deletion: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "tr": "<p>Silinmeye uygun: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "kk": "<p>Жоюға жарамды: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "uz": "<p>Oʻchirishga yaroqli: <b>{n}</b> {files}, <b>{size}</b>.</p>",
        "az": "<p>Silinməyə uyğun: <b>{n}</b> {files}, <b>{size}</b>.</p>",
    },
    "del.blocked": {
        "ru": "<p>Отклонено: <b>{n}</b>. Удаляется только то, у чего сошёлся хеш и что лежит в проверенном архиве. Файлы с дырками не удаляются никогда.</p>",
        "en": "<p>Rejected: <b>{n}</b>. Only files whose hash matched and that are in a verified archive get deleted. Files with gaps are never deleted.</p>",
        "tr": "<p>Reddedilen: <b>{n}</b>. Yalnızca özeti tutan ve doğrulanmış arşivde bulunan dosyalar silinir. Boşluklu dosyalar asla silinmez.</p>",
        "kk": "<p>Қабылданбады: <b>{n}</b>. Тек хэші сәйкес келген және тексерілген мұрағатта жатқандар жойылады. Олқылықты файлдар ешқашан жойылмайды.</p>",
        "uz": "<p>Rad etildi: <b>{n}</b>. Faqat xeshi mos kelgan va tekshirilgan arxivda yotganlar oʻchiriladi. Boʻshliqli fayllar hech qachon oʻchirilmaydi.</p>",
        "az": "<p>Rədd edildi: <b>{n}</b>. Yalnız heşi uyğun gələn və yoxlanılmış arxivdə olanlar silinir. Boşluqlu fayllar heç vaxt silinmir.</p>",
    },
    "del.reasonCol": {"ru": "почему отклонён", "en": "why rejected", "tr": "neden reddedildi", "kk": "неге қабылданбады", "uz": "nega rad etildi", "az": "niyə rədd edildi"},
    "del.pcsCol": {"ru": "шт", "en": "pcs", "tr": "adet", "kk": "дана", "uz": "dona", "az": "ədəd"},
    "del.sample": {"ru": "Например:", "en": "For example:", "tr": "Örneğin:", "kk": "Мысалы:", "uz": "Masalan:", "az": "Məsələn:"},
    "del.go": {
        "ru": "Удалить {n} шт безвозвратно", "en": "Delete {n} permanently",
        "tr": "{n} tanesini kalıcı olarak sil", "kk": "{n} дананы қайтарымсыз жою",
        "uz": "{n} donani qaytarib boʻlmaydigan tarzda oʻchirish", "az": "{n} ədədi həmişəlik sil",
    },
    "del.confirm": {
        "ru": "Последнее подтверждение: безвозвратно удалить {n} {files} из облака Яндекса?",
        "en": "Final confirmation: permanently delete {n} {files} from Yandex cloud?",
        "tr": "Son onay: Yandex bulutundan {n} {files} kalıcı olarak silinsin mi?",
        "kk": "Соңғы растау: Яндекс бұлтынан {n} {files} қайтарымсыз жою керек пе?",
        "uz": "Soʻnggi tasdiq: Yandeks bulutidan {n} {files} butunlay oʻchirilsinmi?",
        "az": "Son təsdiq: Yandeks buludundan {n} {files} həmişəlik silinsin?",
    },

    # ── лог ──────────────────────────────────────────────────────────
    "log.title": {"ru": "Лог", "en": "Log", "tr": "Günlük", "kk": "Журнал", "uz": "Jurnal", "az": "Jurnal"},
    "log.empty": {"ru": "Лог пуст.", "en": "The log is empty.", "tr": "Günlük boş.", "kk": "Журнал бос.", "uz": "Jurnal boʻsh.", "az": "Jurnal boşdur."},
    "log.hint": {
        "ru": "Подробность задаётся переменной <code>DRYDOCK_LOG=DEBUG</code> — на DEBUG видно каждый запрос и каждую пробу с кодом ответа.",
        "en": "Verbosity is set by <code>DRYDOCK_LOG=DEBUG</code> — at DEBUG every request and every probe is shown with its response code.",
        "tr": "Ayrıntı düzeyi <code>DRYDOCK_LOG=DEBUG</code> ile ayarlanır — DEBUG'da her istek ve her yoklama yanıt koduyla görünür.",
        "kk": "Егжей-тегжейлілік <code>DRYDOCK_LOG=DEBUG</code> арқылы белгіленеді — DEBUG кезінде әр сұрау мен әр сынақ жауап кодымен көрінеді.",
        "uz": "Batafsillik <code>DRYDOCK_LOG=DEBUG</code> bilan belgilanadi — DEBUG'da har bir soʻrov va har bir sinov javob kodi bilan koʻrinadi.",
        "az": "Təfərrüat <code>DRYDOCK_LOG=DEBUG</code> ilə təyin olunur — DEBUG-da hər sorğu və hər yoxlama cavab kodu ilə görünür.",
    },
    "log.all": {"ru": "всё", "en": "all", "tr": "tümü", "kk": "бәрі", "uz": "hammasi", "az": "hamısı"},
    "log.warnings": {"ru": "предупреждения", "en": "warnings", "tr": "uyarılar", "kk": "ескертулер", "uz": "ogohlantirishlar", "az": "xəbərdarlıqlar"},
    "log.errors": {"ru": "только ошибки", "en": "errors only", "tr": "yalnızca hatalar", "kk": "тек қателер", "uz": "faqat xatolar", "az": "yalnız xətalar"},

    # ── доступ ───────────────────────────────────────────────────────
    "auth.title": {"ru": "Доступ к Яндекс.Диску", "en": "Yandex.Disk access", "tr": "Yandex.Disk erişimi", "kk": "Yandex.Disk қатынауы", "uz": "Yandex.Disk kirishi", "az": "Yandex.Disk girişi"},
    "auth.works": {
        "ru": "Доступ работает: {login} — занято {used} из {total}.",
        "en": "Access works: {login} — {used} used of {total}.",
        "tr": "Erişim çalışıyor: {login} — {total} içinde {used} kullanılıyor.",
        "kk": "Қатынау жұмыс істейді: {login} — {total} ішінен {used} бос емес.",
        "uz": "Kirish ishlaydi: {login} — {total} dan {used} band.",
        "az": "Giriş işləyir: {login} — {total} -dan {used} doludur.",
    },
    "auth.rejected": {
        "ru": "Токен есть, но Диск его не принял: {error}",
        "en": "There is a token, but Disk rejected it: {error}",
        "tr": "Token var ama Disk kabul etmedi: {error}",
        "kk": "Токен бар, бірақ Диск оны қабылдамады: {error}",
        "uz": "Token bor, lekin Disk uni qabul qilmadi: {error}",
        "az": "Token var, amma Disk onu qəbul etmədi: {error}",
    },
    "auth.app": {"ru": "приложение", "en": "application", "tr": "uygulama", "kk": "қолданба", "uz": "ilova", "az": "tətbiq"},
    "auth.appSet": {"ru": "задано, ClientID …{tail}", "en": "set, ClientID …{tail}", "tr": "tanımlı, ClientID …{tail}", "kk": "берілген, ClientID …{tail}", "uz": "berilgan, ClientID …{tail}", "az": "təyin edilib, ClientID …{tail}"},
    "auth.appUnset": {"ru": "не задано", "en": "not set", "tr": "tanımsız", "kk": "берілмеген", "uz": "berilmagan", "az": "təyin edilməyib"},
    "auth.token": {"ru": "токен", "en": "token", "tr": "token", "kk": "токен", "uz": "token", "az": "token"},
    "auth.refresh": {"ru": "продление", "en": "refresh", "tr": "yenileme", "kk": "жаңарту", "uz": "yangilash", "az": "yeniləmə"},
    "auth.until": {"ru": "действует до", "en": "valid until", "tr": "geçerlilik", "kk": "жарамды", "uz": "amal qiladi", "az": "etibarlıdır"},
    "auth.scope": {"ru": "права", "en": "scope", "tr": "izinler", "kk": "құқықтар", "uz": "huquqlar", "az": "hüquqlar"},
    "auth.store": {"ru": "хранилище", "en": "store", "tr": "depo", "kk": "қойма", "uz": "ombor", "az": "anbar"},
    "auth.encryption": {"ru": "шифрование", "en": "encryption", "tr": "şifreleme", "kk": "шифрлау", "uz": "shifrlash", "az": "şifrələmə"},
    "auth.dpapi": {
        "ru": "DPAPI — ключ держит Windows, привязан к твоей учётной записи",
        "en": "DPAPI — the key is held by Windows and bound to your account",
        "tr": "DPAPI — anahtarı Windows tutar, hesabınıza bağlıdır",
        "kk": "DPAPI — кілтті Windows ұстайды, тіркелгіңізге байланған",
        "uz": "DPAPI — kalitni Windows ushlaydi, hisobingizga bogʻlangan",
        "az": "DPAPI — açarı Windows saxlayır, hesabınıza bağlıdır",
    },
    "auth.yes": {"ru": "есть", "en": "yes", "tr": "var", "kk": "бар", "uz": "bor", "az": "var"},
    "auth.no": {"ru": "нет", "en": "no", "tr": "yok", "kk": "жоқ", "uz": "yoʻq", "az": "yoxdur"},
    "auth.step1": {"ru": "1. Приложение", "en": "1. Application", "tr": "1. Uygulama", "kk": "1. Қолданба", "uz": "1. Ilova", "az": "1. Tətbiq"},
    "auth.step1note": {
        "ru": "Создаётся один раз на <a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a>. В его настройках должен быть указан Redirect URI, ровно тот, что выше. Права: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code>, и <code>cloud_api:disk.write</code> — последнее нужно только чтобы удалять спасённое из облака.",
        "en": "Created once at <a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a>. Its settings must list the Redirect URI exactly as shown above. Scopes: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code>, and <code>cloud_api:disk.write</code> — the last one only to delete rescued files from the cloud.",
        "tr": "<a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a> üzerinde bir kez oluşturulur. Ayarlarında Redirect URI tam olarak yukarıdaki gibi yazmalı. İzinler: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code> ve <code>cloud_api:disk.write</code> — sonuncusu yalnızca kurtarılanları buluttan silmek için.",
        "kk": "<a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a> сайтында бір рет жасалады. Оның параметрлерінде жоғарыдағыдай Redirect URI көрсетілуі керек. Құқықтар: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code> және <code>cloud_api:disk.write</code> — соңғысы тек құтқарылғанды бұлттан жою үшін.",
        "uz": "<a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a> saytida bir marta yaratiladi. Uning sozlamalarida yuqoridagidek Redirect URI koʻrsatilishi kerak. Huquqlar: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code> va <code>cloud_api:disk.write</code> — oxirgisi faqat qutqarilganni bulutdan oʻchirish uchun.",
        "az": "<a href=\"https://oauth.yandex.ru\" target=\"_blank\" rel=\"noreferrer\">oauth.yandex.ru</a> saytında bir dəfə yaradılır. Onun parametrlərində yuxarıdakı kimi Redirect URI göstərilməlidir. Hüquqlar: <code>cloud_api:disk.read</code>, <code>cloud_api:disk.info</code> və <code>cloud_api:disk.write</code> — sonuncusu yalnız xilas ediləni buluddan silmək üçün.",
    },
    "auth.placeholderSet": {
        "ru": "задан — заполни, чтобы заменить", "en": "set — fill in to replace",
        "tr": "tanımlı — değiştirmek için doldurun", "kk": "берілген — ауыстыру үшін толтырыңыз",
        "uz": "berilgan — almashtirish uchun toʻldiring", "az": "təyin edilib — dəyişmək üçün doldurun",
    },
    "auth.save": {"ru": "Сохранить приложение", "en": "Save application", "tr": "Uygulamayı kaydet", "kk": "Қолданбаны сақтау", "uz": "Ilovani saqlash", "az": "Tətbiqi saxla"},
    "auth.saved": {"ru": "Записано в шифрованное хранилище.", "en": "Saved to the encrypted store.", "tr": "Şifreli depoya kaydedildi.", "kk": "Шифрланған қоймаға жазылды.", "uz": "Shifrlangan omborga yozildi.", "az": "Şifrələnmiş anbara yazıldı."},
    "auth.needBoth": {"ru": "Нужны и ClientID, и Client secret.", "en": "Both ClientID and Client secret are required.", "tr": "Hem ClientID hem Client secret gerekli.", "kk": "ClientID де, Client secret те қажет.", "uz": "ClientID ham, Client secret ham kerak.", "az": "Həm ClientID, həm Client secret lazımdır."},
    "auth.step2": {"ru": "2. Согласие", "en": "2. Consent", "tr": "2. Onay", "kk": "2. Келісім", "uz": "2. Rozilik", "az": "2. Razılıq"},
    "auth.step2note": {
        "ru": "Откроется страница Яндекса. Пароль вводится только там — программа его не видит и не хранит: обратно приходит код, который обменивается на токен.",
        "en": "A Yandex page will open. The password is entered only there — the program neither sees nor stores it: a code comes back and is exchanged for a token.",
        "tr": "Bir Yandex sayfası açılır. Parola yalnızca orada girilir — program onu ne görür ne saklar: geri bir kod gelir ve token ile değiştirilir.",
        "kk": "Яндекс беті ашылады. Құпия сөз тек сонда енгізіледі — бағдарлама оны көрмейді және сақтамайды: кері код келеді, ол токенге ауыстырылады.",
        "uz": "Yandeks sahifasi ochiladi. Parol faqat oʻsha yerda kiritiladi — dastur uni koʻrmaydi va saqlamaydi: qaytib kod keladi, u tokenga almashtiriladi.",
        "az": "Yandeks səhifəsi açılacaq. Parol yalnız orada daxil edilir — proqram onu nə görür, nə saxlayır: geri kod gəlir və tokenlə dəyişdirilir.",
    },
    "auth.openConsent": {"ru": "Открыть страницу согласия", "en": "Open consent page", "tr": "Onay sayfasını aç", "kk": "Келісім бетін ашу", "uz": "Rozilik sahifasini ochish", "az": "Razılıq səhifəsini aç"},
    "auth.manual": {"ru": "…без Redirect URI", "en": "…without Redirect URI", "tr": "…Redirect URI olmadan", "kk": "…Redirect URI-сіз", "uz": "…Redirect URI'siz", "az": "…Redirect URI olmadan"},
    "auth.refreshBtn": {"ru": "Продлить токен", "en": "Refresh token", "tr": "Tokenı yenile", "kk": "Токенді жаңарту", "uz": "Tokenni yangilash", "az": "Tokeni yenilə"},
    "auth.forget": {"ru": "Забыть токен", "en": "Forget token", "tr": "Tokenı unut", "kk": "Токенді ұмыту", "uz": "Tokenni unutish", "az": "Tokeni unut"},
    "auth.forgetConfirm": {
        "ru": "Забыть токен? Данные приложения останутся.",
        "en": "Forget the token? The application data will remain.",
        "tr": "Token unutulsun mu? Uygulama verileri kalır.",
        "kk": "Токенді ұмыту керек пе? Қолданба деректері қалады.",
        "uz": "Token unutilsinmi? Ilova maʼlumotlari qoladi.",
        "az": "Token unudulsun? Tətbiq məlumatları qalacaq.",
    },
    "auth.waitReturn": {
        "ru": "Разреши доступ в открывшейся вкладке — она сама вернётся сюда. Потом нажми «Закрыть» и перезагрузи страницу.",
        "en": "Grant access in the tab that opened — it will come back here by itself. Then press “Close” and reload the page.",
        "tr": "Açılan sekmede erişime izin verin — kendiliğinden buraya döner. Sonra “Kapat”a basıp sayfayı yenileyin.",
        "kk": "Ашылған қойындыда қатынауға рұқсат беріңіз — ол өзі осында оралады. Содан кейін «Жабу» басып, бетті қайта жүктеңіз.",
        "uz": "Ochilgan varaqda kirishga ruxsat bering — u oʻzi shu yerga qaytadi. Keyin “Yopish” bosing va sahifani qayta yuklang.",
        "az": "Açılan vərəqdə girişə icazə verin — o özü bura qayıdacaq. Sonra “Bağla” basıb səhifəni yeniləyin.",
    },
    "auth.codeHint": {
        "ru": "Яндекс покажет код на странице. Вставь его:",
        "en": "Yandex will show a code on the page. Paste it:",
        "tr": "Yandex sayfada bir kod gösterecek. Yapıştırın:",
        "kk": "Яндекс бетте кодты көрсетеді. Оны қойыңыз:",
        "uz": "Yandeks sahifada kodni koʻrsatadi. Uni joylashtiring:",
        "az": "Yandeks səhifədə kod göstərəcək. Onu yapışdırın:",
    },
    "auth.codePh": {"ru": "код подтверждения", "en": "confirmation code", "tr": "onay kodu", "kk": "растау коды", "uz": "tasdiqlash kodi", "az": "təsdiq kodu"},
    "auth.codeGo": {"ru": "Обменять на токен", "en": "Exchange for token", "tr": "Token ile değiştir", "kk": "Токенге ауыстыру", "uz": "Tokenga almashtirish", "az": "Tokenlə dəyişdir"},
    "auth.gotToken": {"ru": "Токен получен.", "en": "Token received.", "tr": "Token alındı.", "kk": "Токен алынды.", "uz": "Token olindi.", "az": "Token alındı."},
    "auth.refreshed": {"ru": "Продлён.", "en": "Refreshed.", "tr": "Yenilendi.", "kk": "Жаңартылды.", "uz": "Yangilandi.", "az": "Yeniləndi."},
    "auth.redirectUri": {"ru": "Redirect URI", "en": "Redirect URI", "tr": "Redirect URI", "kk": "Redirect URI", "uz": "Redirect URI", "az": "Redirect URI"},
}


def build() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    missing: list[str] = []
    for key, variants in S.items():
        for lang in LANGS:
            value = variants.get(lang)
            if value is None:
                missing.append(f"{key}:{lang}")
                continue
            if isinstance(value, dict):      # формы множественного числа
                for form, text in value.items():
                    out[lang][f"{key}.{form}"] = text
            else:
                out[lang][key] = value
    if missing:
        raise SystemExit("нет перевода: " + ", ".join(missing[:20]))
    return out


def main() -> int:
    """Собрать словари. С --check только сверить, ничего не записывая."""
    check = "--check" in sys.argv[1:]
    built = build()
    stale = []
    for lang, dictionary in built.items():
        path = OUT / f"{lang}.json"
        text = json.dumps(dictionary, ensure_ascii=False, indent=1,
                          sort_keys=True)
        if check:
            current = path.read_text(encoding="utf-8") if path.is_file() else ""
            if current != text:
                stale.append(path.name)
            continue
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"{path.name}: {len(dictionary)} строк")
    if stale:
        print("словари разошлись с make_i18n.py: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
