# Drydock

Спасает файлы с Яндекс.Диска, когда облако перестаёт их отдавать: описывает
коллекцию, проверяет доступность, качает то, что отдаётся, сверяет хеши,
пакует в архивы.

Сделана под свою коллекцию: в первый день вытащила половину, сейчас — почти
98%. Файлы то отдаются, то нет, поэтому круг лучше не выключать.

**Русский** · [English](docs/README.en.md) · [Türkçe](docs/README.tr.md) ·
[Қазақша](docs/README.kk.md) · [Oʻzbekcha](docs/README.uz.md) ·
[Azərbaycanca](docs/README.az.md)

MIT · Windows · macOS · Linux · Python 3.12+ · не связан с Яндексом

[![site](https://img.shields.io/badge/site-venedicus.github.io%2Fdrydock-4fb477)](https://venedicus.github.io/drydock/)
![release](https://img.shields.io/github/v/release/venedicus/drydock?color=4fb477)
![stars](https://img.shields.io/github/stars/venedicus/drydock?color=5c9ded)
![last commit](https://img.shields.io/github/last-commit/venedicus/drydock)

![Демо: опись, архив, здоровье, инструменты, масштаб](docs/images/demo.ru.gif)

## Что умеет

| Действие | Что делает |
|---|---|
| **Опись** | обходит облако и записывает имя, размер, хеши и место в дереве — включая файлы, которые уже не скачать |
| **Проба** | проверяет доступность без скачивания: первый и последний байт |
| **Круг** | качает всё, что отдаётся, и перепроверяет недоступное, пока не остановишь |
| **Архив** | пакует спасённое в тома 3.9 ГБ, 1.9 ГБ или одним файлом |
| **Удаление** | освобождает облако тем, что уже проверено; три режима: проверенное, архивированное, выбранное вручную |
| **Здоровье** | показывает, почему не выходит: причины отказов, узлы, задачи |
| **Экспорт** | выгружает опись в CSV или JSON: путь, размер, доступность, хеши, где лежит спасённая копия |

Ещё: превью, учёт файлов, спасённых вручную, сверка зеркала с диском,
автопилот, командная палитра `Ctrl+K`, шесть языков, тёмная и светлая темы.

## Как поставить

**Готовый файл** — `Drydock.exe` из [релизов](https://github.com/venedicus/drydock/releases/latest).
Python не нужен, нужен только [7-Zip](https://www.7-zip.org/).

**Из исходников** — Python 3.12+, 7-Zip и любая из трёх систем:

```powershell
# Windows
git clone https://github.com/venedicus/drydock.git
cd drydock
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

```bash
# macOS и Linux
git clone https://github.com/venedicus/drydock.git
cd drydock
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

На Linux 7-Zip ставится пакетом `p7zip-full`, на macOS — `brew install sevenzip`.

Запуск — `Drydock.exe` на Windows, `./Drydock.sh` на macOS и Linux, либо
`drydock app` из любого места. Окно открывается на `http://127.0.0.1:8765`.

1. **Доступ** — вставить токен из [полигона Яндекса](https://yandex.ru/dev/disk/poligon/)
   или задать `YANDEX_DISK_TOKEN`.
2. **Настройки** — выбрать папку для `files/`, `meta/`, `archives/`, `catalog.db`.
3. **Опись** — дождаться конца.
4. **Круг** — оставить работать.

## Документы

- [Как это работает](docs/how-it-works.md) — опись, проба, выгрузка, проверка, архив, удаление
- [Ограничения](docs/limitations.md) — чего программа не делает и почему
- [Сравнение](docs/comparison.md) — Drydock, клиент синхронизации и rclone
- [Участие](CONTRIBUTING.md) · [Безопасность](SECURITY.md) · [Изменения](CHANGELOG.md)

## Чем помочь

- **Поставить звезду** — по ней проект находят другие.
- **Поблагодарить автора** — [страница с реквизитами](https://venedicus.github.io/drydock/).
- **Рассказать, если помогло** — issue с историей: сколько файлов, что не вышло.
- **Сообщить, где числа разошлись** — это важнее новых возможностей.
- **Поправить перевод** — языков шесть, любой может отстать от кода.

[![YooMoney](https://img.shields.io/badge/YooMoney-4100117869777196-8b3ffd)](https://yoomoney.ru/to/4100117869777196) [![Bitcoin](https://img.shields.io/badge/Bitcoin-bc1qaj3jllq...prp2-f7931a?logo=bitcoin&logoColor=white)](https://venedicus.github.io/drydock/) [![USDT](https://img.shields.io/badge/USDT-TRC--20-26a17b?logo=tether&logoColor=white)](https://venedicus.github.io/drydock/) [![TON](https://img.shields.io/badge/TON-UQBKSMU3...Grx1-0098ea?logo=ton&logoColor=white)](https://venedicus.github.io/drydock/) [![XMR](https://img.shields.io/badge/XMR-45LuFsk9...dsWPF-f26822?logo=monero&logoColor=white)](https://venedicus.github.io/drydock/)

<details>
<summary>Реквизиты для перевода</summary>

| Сеть | Адрес |
|---|---|
| Bitcoin (BTC, SegWit) | `bc1qaj3jllqse90sqcrfvtyv5ll7le2guh0q30prp2` |
| Bitcoin Lightning | `venedicus@cake.cash` |
| Ethereum (ETH, ERC-20) | `0x1e728B3568c9072A749694dEa116b1c8331fD43a` |
| BNB Chain (BNB, BEP-20) | `0x1e728B3568c9072A749694dEa116b1c8331fD43a` |
| Polygon (POL) | `0x1e728B3568c9072A749694dEa116b1c8331fD43a` |
| TON (TON, USDT) | `UQBKSMU3B9OFfaqWK3iQBCyifZjCEgF8m4kBsO-Tu5U4Grx1` |
| Tron (TRX, USDT TRC-20) | `TMibQMbptanys3JVgZxpHucQLZsWGTihzg` |
| Solana (SOL, SPL) | `5xb56pkcUk473d13MKADLdBNtuA2v4qFukSpWermZhm3` |
| Dogecoin (DOGE) | `D7VGb1PsLqr5RSnFmiwCz81zTq9gPsUTng` |
| Litecoin (LTC) | `ltc1qp0wfw2hezl94c4c3cl6yeya4wcczck2ttjaun8` |
| Monero (XMR) | `45LuFsk9rr7JwepcsfaspeTwyUVy7QbbWUbA1hsBj374h3BPhyPvpqWLVfQM9kDJBddZKsQcNbDEhS3ZTdoritJvGLdsWPF` |

Ethereum, BNB Chain и Polygon используют один адрес — сеть выбирается при отправке. Карта, СБП и ЮMoney: [страница перевода](https://yoomoney.ru/to/4100117869777196).

</details>

---

© 2026 venedicus · MIT · «Яндекс.Диск» — товарный знак правообладателя,
проект с Яндексом не связан.
