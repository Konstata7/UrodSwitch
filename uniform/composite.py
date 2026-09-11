from PIL import Image

from . import skin_formats
from .constants import (
    ARM_MAIN,
    body_main,
    head_main,
    left_leg_main,
    right_leg_main,
)


def uniform_composite(inp1: Image.Image, inp2: Image.Image,
                      skin_format: str = skin_formats.DEFAULT) -> Image.Image:
    """
    Наложение формы на скин.

    ``skin_format`` задаёт разметку рук: у slim-скинов руки на пиксель уже,
    поэтому и область формы, и стираемый второй слой (рукава) считаются
    по slim-разметке — см. ``ARM_MAIN`` в ``uniform/constants.py``.

    Логика одна и та же для обоих форматов: пиксель формы внутри области тела
    стирает пиксель второго слоя на том же месте (куртка/рукава/штанины),
    после чего форма накладывается на скин целиком.
    """
    if not skin_formats.is_valid(skin_format):
        raise ValueError(f"Неизвестный формат скина: {skin_format!r}")

    right_arm, left_arm = ARM_MAIN[skin_format]

    inp1 = inp1.convert("RGBA")
    inp2 = inp2.convert("RGBA")
    inp1_edit = inp1.copy()
    t = []
    for x in range(64):
        for y in range(64):
            pix = inp2.getpixel((x, y))
            try:
                if sum(pix) != 0:
                    t.append((x, y))
            except TypeError:
                return inp1
    for i in t:
        if i in head_main:
            inp1_edit.putpixel((i[0] + 32, i[1]), (0, 0, 0, 0))
        elif i in body_main:
            inp1_edit.putpixel((i[0], i[1] + 16), (0, 0, 0, 0))
        elif i in left_arm:
            inp1_edit.putpixel((i[0] + 16, i[1]), (0, 0, 0, 0))
        elif i in left_leg_main:
            inp1_edit.putpixel((i[0] - 16, i[1]), (0, 0, 0, 0))
        elif i in right_arm:
            inp1_edit.putpixel((i[0], i[1] + 16), (0, 0, 0, 0))
        elif i in right_leg_main:
            inp1_edit.putpixel((i[0], i[1] + 16), (0, 0, 0, 0))
    out = Image.alpha_composite(inp1_edit, inp2)
    return out
