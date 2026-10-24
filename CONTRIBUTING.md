# Участие

[← README](README.md)

## Настройка

```powershell
git clone https://github.com/venedicus/drydock.git
cd drydock
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Проверки перед отправкой

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check drydock tests tools
.venv\Scripts\python.exe tools/make_i18n.py --check
```

Тесты запускаются и напрямую (`python tests/test_core.py`) — без pytest.

## Переводы

Строки не правятся в `web/i18n/*.json`: они собираются из `tools/make_i18n.py`.

```powershell
.venv\Scripts\python.exe tools/make_i18n.py
```

Требования: ключ из кода есть в словаре; подстановки (`{n}`, `{size}`)
совпадают во всех языках; у русского три формы числа. Это проверяет
`tests/test_i18n.py`.

## Стиль

- `ruff`, длина строки 100.
- Комментарии объясняют **почему**, а не что.
- В строках интерфейса нет дат и чисел: «на 21 октября вернулось 1371»
  через месяц станет ложью. Замеры — в комментариях, с датой.

## Данные

В репозитории не должно быть чужих данных: путей вида `C:\Users\…`, имён
файлов из реальных коллекций, токенов, скриншотов с личными папками.
Скриншоты снимаются с демонстрационной базы.

## Pull request

Одна задача — один PR. В описании: что было не так, что изменилось, как
проверить. Менялось поведение — обновите `CHANGELOG.md`; менялись строки —
пересоберите словари.

Отправляя PR, вы соглашаетесь, что вклад распространяется на условиях MIT.
