# Uniform Applicator

Одностраничный сайт на Django с направленным функционалом: пользователь
загружает **скин** и **форму (uniform)** — сервер накладывает форму на скин,
после чего результат можно скачать PNG или **сразу открыть в веб-редакторе
[Blockbench](https://web.blockbench.net/)** для ручной доработки.

Обработка изображений — Pillow, логика наложения лежит в `uniform/composite.py`
(координаты областей тела — в `uniform/constants.py`).

## Быстрый старт

Проект рассчитан на Python 3.12. Виртуальное окружение уже есть в `.venv`
(Django 6.1.1, Pillow 12.3.0). Для чистого окружения:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # или: & .\.venv\Scripts\python.exe -m pip ...
pip install -r requirements.txt
```

Применить миграции и запустить сервер:

```powershell
python manage.py migrate
python manage.py runserver
```

Откройте <http://127.0.0.1:8000/> — это и есть единственная страница сайта.

Опционально — админка:

```powershell
python manage.py createsuperuser
# затем http://127.0.0.1:8000/admin/
```

Тесты:

```powershell
python manage.py test
```

## Как пользоваться страницей

1. **Скин** — PNG 64×64 (стандартный атлас скина Minecraft).
2. **Форма** — PNG 64×64 **на прозрачном фоне**. Нарисованные области
   распознаются по координатам из `uniform/constants.py` как части тела:
   голова, туловище, руки, ноги.
3. Жмём «Наложить форму» — страница не перезагружается (AJAX), появляется
   результат и кнопки «Скачать PNG» и **«Редактировать в Blockbench Web»**.

Результаты сохраняются в `media/processed/` (каталог в `.gitignore`).
В режиме отладки файлы отдаёт сам Django (`config/urls.py`), в проде
медиафайлы должен раздавать веб-сервер.

## Открытие результата в Blockbench Web

Кнопка «Редактировать в Blockbench Web» ведёт на маршрут
`/blockbench/<файл>.png/` (`uniform/views.blockbench_editor`), который читает
готовый скин и **редиректит в веб-приложение Blockbench** уже с загруженной
картинкой — пользователь сразу попадает в редактор скина и может дорисовать
его кистью.

Скин передаётся как готовый проект Blockbench (`uniform/blockbench.py`)
штатными параметрами веб-приложения
([документация](https://blockbench.net/wiki/docs/url-parameters/)):

| Параметр | Значение |
| --- | --- |
| `loadtype` | `json` — открыть готовый проект |
| `loadname` | `uniform_applicator.bbmodel` — имя проекта в редакторе |
| `loaddata` | JSON проекта `.bbmodel` (модель игрока + PNG в base64) |

В проекте важны три поля: `meta.model_format = "skin"` — какой формат открыть;
`skin_model` — какую модель игрока развернуть (кубы Blockbench строит сам,
`Codecs.skin_model.rebuild`); `textures[0].source` — сам скин в виде data-URL.

**Почему не `loadtype=minecraft_skin`.** Этот параметр открывает диалог
«New Skin», но присланную картинку в него не подставляет: в исходниках
Blockbench (`js/web.js`) значение из URL кладётся в поле `texture`, а диалог
скина читает это поле только для модели «Flat texture» — для остальных моделей
текстура берётся из `texture_file`, то есть из файла, который пользователь
выбирает вручную (`js/formats/minecraft/skin.ts`, `onConfirm`). Поэтому кнопка
и приводила к пустому созданию скина без текстуры.

Модель игрока по умолчанию — с широкими руками (`steve`, «Player - Wide»).
Для скина с тонкими руками переключитесь в Blockbench: меню **Skin** →
«Convert Player Model» (`convert_minecraft_skin_variant`).

Маршрут принимает только файлы результатов вида `<uuid4>.png` из
`media/processed/`, поэтому через него нельзя прочитать произвольные файлы
на диске (проверяется регуляркой и наличием файла — см. тесты).

## Структура проекта

```
manage.py                     # точка входа (DJANGO_SETTINGS_MODULE=config.settings)
config/                       # настройки проекта
  settings.py                 # окружение: DJANGO_SECRET_KEY/DEBUG/ALLOWED_HOSTS
  urls.py                     # '/' -> uniform, '/admin/', раздача /media/ в DEBUG
uniform/                      # приложение-одностраничник
  views.py                    # GET — форма, POST — обработка; редирект в Blockbench
  urls.py                     # '' -> views.index, 'blockbench/<файл>/' -> views.blockbench_editor
  services.py                 # валидация файлов, наложение, сохранение результата
  composite.py                # uniform_composite(skin, uniform) — ядро наложения
  constants.py                # координаты областей тела (голова/туловище/руки/ноги)
  blockbench.py               # сборка .bbmodel-проекта и ссылки для Blockbench Web
  templates/uniform/index.html# разметка страницы (заполняется под задачу)
  static/uniform/
    css/style.css             # стили страницы
    js/app.js                 # логика формы, результата и ссылки на Blockbench
media/processed/              # результаты (создаётся автоматически)
requirements.txt
```

## Куда «заполнять» проект

* Контент и секции страницы — `uniform/templates/uniform/index.html`
  (сейчас есть блоки «Как это работает» и «О сервисе» как заглушки).
* Внешний вид — CSS-переменные в `uniform/static/uniform/css/style.css`.
* Логика наложения/валидации — `uniform/services.py` и `uniform/composite.py`.
* Интеграция с Blockbench — `uniform/blockbench.py` и `views.blockbench_editor`
  (константы `SKIN_MODEL` / `SKIN_POSE` / `PROJECT_NAME` — в начале модуля).
* При необходимости моделей — `uniform/models.py` + `makemigrations`.
* Общие шаблоны (base.html и т.п.) — каталог `templates/` в корне проекта.

## Замечания

* Оба изображения обязаны быть ровно 64×64 — иначе сервер вернёт ошибку.
* Требования к прозрачности формы проверяются при загрузке
  (`uniform/services.load_uniform`).
* Секретный ключ и DEBUG по умолчанию пригодны только для разработки;
  в проде задайте `DJANGO_SECRET_KEY`, выключите `DJANGO_DEBUG` и
  заполните `DJANGO_ALLOWED_HOSTS`.
