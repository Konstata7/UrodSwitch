"""
Представления одностраничника.

GET  '/'  — страница с выбором формата скина и формой загрузки файлов.
POST '/'  — обработка загрузки: наложение формы на скин.
GET  '/skin/<ник>/' — актуальный скин игрока по нику (для предпросмотра).
GET  '/blockbench/<файл>/' — переход в веб-редактор Blockbench
     с уже загруженным получившимся скином (готовый проект .bbmodel,
     подробности и причины — в uniform/blockbench.py).

Порядок работы: скин можно дать файлом или ником игрока, а **формат classic/slim
приложение определяет само** — у скина по нику его сообщает Mojang, у файла он
считается по текстуре (``services.detect_skin_format``). Формат из формы — это
ручной выбор пользователя: если он отличается от автоопределения, он главнее.
Формат определяет и разметку рук при наложении формы, и модель игрока
в Blockbench.

Ответ на POST:
  * при обычной отправке формы — та же страница с блоком результата/ошибки;
  * для AJAX-запросов (заголовок X-Requested-With: XMLHttpRequest) — JSON:
        {"ok": true,  "url": "/media/processed/<uuid>_<формат>.png",
         "file": "<uuid>_<формат>.png", "format": "classic",
         "format_label": "Classic — широкие руки, 4 пикселя — модель Steve",
         "skin_source": "file" | "nickname", "nickname": "Notch",
         "format_note": "…", "download": "<имя>.png",
         "blockbench": "/blockbench/<файл>/"}
        {"ok": false, "error": "текст ошибки"}
"""

import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from . import blockbench as blockbench_web
from . import minecraft_profile
from . import services
from . import skin_formats
from .services import ImageProcessError

TEMPLATE = "uniform/index.html"

# Имя файла, под которым браузер сохранит результат при скачивании.
RESULT_FILENAME = "urodswitch.png"

# В имени файла результата зашит формат скина: <uuid4>_<формат>.png.
# Разрешаем открывать в Blockbench только такие файлы результатов.
RESULT_FILE_RE = re.compile(
    rf"^[0-9a-f]{{32}}_({'|'.join(skin_formats.ALL)})\.png$"
)


def index(request):
    """Единственная страница: GET — форма, POST — обработка файлов."""
    if request.method == "POST":
        return _handle_post(request)
    return render(request, TEMPLATE, _base_context())


def blockbench_editor(request, filename):
    """
    Редирект в веб-редактор Blockbench с готовым скином.

    Скин отдаётся как готовый проект Blockbench (``loadtype=json`` + .bbmodel):
    в нём лежит и модель игрока, и наша PNG-текстура, поэтому редактор
    открывается сразу с загруженной картинкой. Штатный параметр
    ``loadtype=minecraft_skin`` для этого не годится — он открывает пустой
    диалог «New Skin» (разбор причин — в uniform/blockbench.py).

    Формат скина берётся из имени файла результата и определяет модель
    игрока: classic — Steve, slim — Alex.
    """
    match = RESULT_FILE_RE.match(filename)
    if match is None:
        raise Http404("Неизвестный файл результата.")

    path = Path(settings.MEDIA_ROOT) / services.OUTPUT_SUBDIR / filename
    if not path.is_file():
        raise Http404("Файл результата не найден.")

    skin_format = match.group(1)
    project = blockbench_web.build_project(
        path.read_bytes(),
        services.SIZE,
        model=blockbench_web.SKIN_MODELS[skin_format],
    )
    return HttpResponseRedirect(blockbench_web.editor_url(project))


def skin_by_nickname(request, nickname):
    """
    Актуальный скин игрока по нику — для предпросмотра на странице.

    Скин берётся с серверов Mojang (см. ``uniform/minecraft_profile.py``):
    те же данные, что показывает NameMC. Возвращает JSON с картинкой
    в виде data-URL и определённым форматом скина (classic/slim).
    """
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "Метод не поддерживается."}, status=405)

    try:
        profile = minecraft_profile.fetch_skin(nickname)
        skin = services.load_skin_bytes(
            profile.skin_png, name=f"Скин игрока {profile.nickname}"
        )
    except (minecraft_profile.ProfileError, ImageProcessError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "nickname": profile.nickname,
            "uuid": profile.uuid,
            "format": profile.skin_format,
            "format_label": _format_label(profile.skin_format),
            "skin": services.to_data_url(skin),
        }
    )


def _base_context(**extra) -> dict:
    """Контекст шаблона: варианты формата скина + всё, что передал вызывающий."""
    context = {
        "skin_format_choices": [
            {
                "value": value,
                "label": skin_formats.LABELS[value],
                "description": skin_formats.DESCRIPTIONS[value],
            }
            for value in skin_formats.ALL
        ],
    }
    context.update(extra)
    return context


def _handle_post(request):
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    skin_file = request.FILES.get("skin")
    uniform_file = request.FILES.get("uniform")
    # Ник: подтверждённый (skin_nickname — скин по нему уже найден и показан)
    # или просто вписанный в поле (например, когда JS выключен).
    nickname = (
        request.POST.get("skin_nickname") or request.POST.get("nickname") or ""
    ).strip()
    # Формат: у скина по нику его сообщает Mojang, у файла определяем по картинке.
    # Значение из формы — это ручной выбор пользователя, он главнее автоопределения.
    skin_format = (request.POST.get("skin_format") or "").strip().lower()

    try:
        payload = _process_upload(skin_file, uniform_file, skin_format, nickname)
    except (ImageProcessError, minecraft_profile.ProfileError) as exc:
        payload = {"ok": False, "error": str(exc)}

    # AJAX-запросу отдаём JSON с кодом 400 при ошибке,
    # обычной отправке — перерисованную страницу (код 200, ошибка в контексте).
    if is_ajax:
        return JsonResponse(payload, status=200 if payload["ok"] else 400)

    context = {"selected_format": skin_format, "nickname": nickname}
    if payload.get("ok"):
        context["result_url"] = payload["url"]
        context["result_name"] = payload["download"]
        context["result_file"] = payload["file"]
        context["result_format_label"] = _format_label(payload["format"])
        context["result_note"] = payload["format_note"]
        # Ник, который реально использовали (для повторной отправки формы).
        context["nickname"] = payload["nickname"]
    else:
        context["error"] = payload.get("error", "Неизвестная ошибка.")
    return render(request, TEMPLATE, _base_context(**context))


def _process_upload(skin_file, uniform_file, skin_format: str, nickname: str) -> dict:
    """
    Готовит скин (файл или ник игрока), накладывает форму, сохраняет результат.

    Формат скина определяется автоматически: у скина по нику его сообщает Mojang
    (``metadata.model``), у файла — по самой картинке
    (``services.detect_skin_format``). Если в форме выбран другой формат вручную,
    его выбор главнее — и об этом пишем в ``format_note``.
    """
    if uniform_file is None:
        raise ImageProcessError(
            "Загрузите форму (PNG 64×64 на прозрачном фоне)."
            if (skin_file is not None or nickname)
            else "Загрузите скин (файлом или по нику) и форму."
        )

    format_note = ""

    if skin_file is not None:
        skin = services.load_skin(skin_file)
        skin_source = "file"
        detected = services.detect_skin_format(skin)
        if skin_formats.is_valid(skin_format) and skin_format != detected:
            format_note = (
                f"По скину определился формат {skin_formats.LABELS[detected]}, "
                f"но вы выбрали {skin_formats.LABELS[skin_format]} — "
                f"обработали в {skin_formats.LABELS[skin_format]}."
            )
        else:
            skin_format = detected
    elif nickname:
        profile = minecraft_profile.fetch_skin(nickname)
        skin = services.load_skin_bytes(
            profile.skin_png, name=f"Скин игрока {profile.nickname}"
        )
        if skin_formats.is_valid(skin_format) and skin_format != profile.skin_format:
            format_note = (
                f"У игрока {profile.nickname} скин формата "
                f"{skin_formats.LABELS[profile.skin_format]} — обработали в нём."
            )
        skin_format = profile.skin_format
        nickname = profile.nickname
        skin_source = "nickname"
    else:
        raise ImageProcessError("Загрузите скин (файлом или по нику) и форму.")

    uniform = services.load_uniform(uniform_file)
    result = services.compose(skin, uniform, skin_format)
    url = services.save_result(result, skin_format)
    filename = url.rsplit("/", 1)[-1]

    return {
        "ok": True,
        "url": url,
        "file": filename,
        "format": skin_format,
        "format_label": _format_label(skin_format),
        "format_note": format_note,
        "skin_source": skin_source,
        "nickname": nickname,
        "download": RESULT_FILENAME,
        "blockbench": reverse("uniform:blockbench", args=[filename]),
    }


def _format_label(skin_format: str) -> str:
    """Подпись формата для блока результата, например «Slim — узкие руки…»."""
    return f"{skin_formats.LABELS[skin_format]} — {skin_formats.DESCRIPTIONS[skin_format]}"
