"""
Представления одностраничника.

GET  '/'  — страница с формой загрузки скина и формы.
POST '/'  — обработка загрузки: наложение формы на скин.
GET  '/blockbench/<файл>.png/' — переход в веб-редактор Blockbench
     с уже загруженным получившимся скином (готовый проект .bbmodel,
     подробности и причины — в uniform/blockbench.py).

Ответ на POST:
  * при обычной отправке формы — та же страница с блоком результата/ошибки;
  * для AJAX-запросов (заголовок X-Requested-With: XMLHttpRequest) — JSON:
        {"ok": true,  "url": "/media/processed/<uuid>.png",
         "download": "<имя>.png", "blockbench": "/blockbench/<uuid>.png/"}
        {"ok": false, "error": "текст ошибки"}
"""

import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from . import blockbench as blockbench_web
from . import services
from .services import ImageProcessError

TEMPLATE = "uniform/index.html"

# Имя файла, под которым браузер сохранит результат при скачивании.
RESULT_FILENAME = "uniform_applicator.png"

# Разрешаем открывать в Blockbench только файлы результатов (uuid4.png).
RESULT_FILE_RE = re.compile(r"^[0-9a-f]{32}\.png$")


def index(request):
    """Единственная страница: GET — форма, POST — обработка файлов."""
    if request.method == "POST":
        return _handle_post(request)
    return render(request, TEMPLATE)


def blockbench_editor(request, filename):
    """
    Редирект в веб-редактор Blockbench с готовым скином.

    Скин отдаётся как готовый проект Blockbench (``loadtype=json`` + .bbmodel):
    в нём лежит и модель игрока, и наша PNG-текстура, поэтому редактор
    открывается сразу с загруженной картинкой. Штатный параметр
    ``loadtype=minecraft_skin`` для этого не годится — он открывает пустой
    диалог «New Skin» (разбор причин — в uniform/blockbench.py).
    """
    if not RESULT_FILE_RE.match(filename):
        raise Http404("Неизвестный файл результата.")

    path = Path(settings.MEDIA_ROOT) / services.OUTPUT_SUBDIR / filename
    if not path.is_file():
        raise Http404("Файл результата не найден.")

    project = blockbench_web.build_project(path.read_bytes(), services.SIZE)
    return HttpResponseRedirect(blockbench_web.editor_url(project))


def _handle_post(request):
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    try:
        payload = _process_upload(request.FILES)
    except ImageProcessError as exc:
        payload = {"ok": False, "error": str(exc)}

    # AJAX-запросу отдаём JSON с кодом 400 при ошибке,
    # обычной отправке — перерисованную страницу (код 200, ошибка в контексте).
    if is_ajax:
        return JsonResponse(payload, status=200 if payload["ok"] else 400)

    context = {}
    if payload.get("ok"):
        context["result_url"] = payload["url"]
        context["result_name"] = payload["download"]
        context["result_file"] = payload["file"]
    else:
        context["error"] = payload.get("error", "Неизвестная ошибка.")
    return render(request, TEMPLATE, context)


def _process_upload(files) -> dict:
    """Валидирует файлы, накладывает форму на скин, сохраняет результат."""
    skin_file = files.get("skin")
    uniform_file = files.get("uniform")

    if skin_file is None or uniform_file is None:
        missing = []
        if skin_file is None:
            missing.append("скин")
        if uniform_file is None:
            missing.append("форму")
        raise ImageProcessError(f"Загрузите {' и '.join(missing)}.")

    skin = services.load_skin(skin_file)
    uniform = services.load_uniform(uniform_file)

    result = services.compose(skin, uniform)
    url = services.save_result(result)
    filename = url.rsplit("/", 1)[-1]

    return {
        "ok": True,
        "url": url,
        "file": filename,
        "download": RESULT_FILENAME,
        "blockbench": reverse("uniform:blockbench", args=[filename]),
    }
