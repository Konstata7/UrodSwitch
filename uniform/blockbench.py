"""
Открытие готового скина в веб-редакторе Blockbench.

Почему не ``loadtype=minecraft_skin``
-------------------------------------
Штатный параметр веб-приложения ``minecraft_skin`` открывает диалог «New Skin»,
но присланную в ``loaddata`` картинку в него не подставляет: в исходниках
Blockbench (``js/web.js``, функция ``loadInfoFromURL``) значение из URL кладётся
в поле ``texture``, а диалог скина читает это поле только для модели
«Flat texture»; для всех остальных моделей текстура берётся из
``texture_file`` — то есть из файла, который пользователь выбирает вручную
(``js/formats/minecraft/skin.ts``, ``onConfirm``). Поэтому кнопка «Редактировать
в Blockbench» приводила к пустому диалогу создания скина.

Как открываем сейчас
--------------------
Отдаём скин как **готовый проект Blockbench** (``loadtype=json`` + файл
``*.bbmodel``). В таком проекте достаточно:

* ``meta.model_format = "skin"`` — какой формат открыть;
* ``skin_model`` — какую модель игрока развернуть (Blockbench сам строит кубы,
  ``Codecs.skin_model.rebuild`` в ``js/formats/bbmodel.js``);
* ``textures[].source`` — наша PNG-картинка в виде data-URL;
* ``resolution`` — размер UV-разметки (64×64).

Пользователь сразу попадает в редактор скина с уже загруженной текстурой.

Документация параметров: https://blockbench.net/wiki/docs/url-parameters/
"""

from __future__ import annotations

import base64
import json
import uuid
from urllib.parse import quote

#: Веб-приложение Blockbench.
BLOCKBENCH_URL = "https://web.blockbench.net/"

#: Формат проекта: скин Minecraft.
BBMODEL_FORMAT = "skin"

#: Версия формата .bbmodel. Минимально достаточная, чтобы файл открывался
#: и в Blockbench 4.x, и в 5.x (кубы/аутлайнер мы не сохраняем — их строит
#: сам Blockbench по полю ``skin_model``).
BBMODEL_FORMAT_VERSION = "4.5"

#: Модель игрока: ``steve`` — широкие руки (Player - Wide).
#: Тонкие руки — ``alex.java``: в Blockbench меняются действием
#: «Convert Player Model» (``convert_minecraft_skin_variant``).
SKIN_MODEL = "steve"

#: Поза по умолчанию — как в диалоге «New Skin» с включённой галочкой Pose.
#: ``none`` — модель в T-позе.
SKIN_POSE = "natural"

#: Имя проекта в редакторе (файл на диске при этом остаётся <uuid>.png).
PROJECT_NAME = "uniform_applicator"
PROJECT_FILENAME = f"{PROJECT_NAME}.bbmodel"


def to_data_url(png_bytes: bytes) -> str:
    """PNG-байты → data-URL, который понимает Blockbench."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_project(
    png_bytes: bytes,
    uv_size: tuple[int, int],
    *,
    name: str = PROJECT_NAME,
    model: str = SKIN_MODEL,
    pose: str = SKIN_POSE,
) -> dict[str, object]:
    """
    Собирает проект Blockbench (.bbmodel) из готового скина.

    ``uv_size`` — размер UV-разметки скина (64×64): по нему Blockbench
    раскладывает развёртку на текстуру. Сама картинка может быть и крупнее.
    """
    width, height = uv_size
    return {
        "meta": {
            "format_version": BBMODEL_FORMAT_VERSION,
            "model_format": BBMODEL_FORMAT,
            "box_uv": True,
        },
        "name": name,
        "resolution": {"width": width, "height": height},
        "skin_model": model,
        "skin_pose": pose,
        "textures": [
            {
                "name": f"{name}.png",
                "id": "0",
                "uuid": str(uuid.uuid4()),
                "uv_width": width,
                "uv_height": height,
                "source": to_data_url(png_bytes),
                "internal": True,
                "visible": True,
            }
        ],
    }


def editor_url(project: dict[str, object], filename: str = PROJECT_FILENAME) -> str:
    """
    Ссылка на веб-приложение Blockbench, открывающая проект.

    Blockbench читает параметры из query-строки, поэтому и JSON проекта,
    и имя файла кодируются целиком (``encodeURIComponent`` по документации).
    """
    payload = json.dumps(project, separators=(",", ":"), ensure_ascii=False)
    return (
        f"{BLOCKBENCH_URL}?loadtype=json"
        f"&loadname={quote(filename, safe='')}"
        f"&loaddata={quote(payload, safe='')}"
    )
