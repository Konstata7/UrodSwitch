from constants import (
    head_main,
    body_main,
    left_arm_main,
    left_leg_main,
    right_arm_main,
    right_leg_main,
)
from PIL import Image


def uniform_composite(inp1: Image.Image, inp2: Image.Image) -> Image.Image:
    """Наложение формы на скин"""
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
        elif i in left_arm_main:
            inp1_edit.putpixel((i[0] + 16, i[1]), (0, 0, 0, 0))
        elif i in left_leg_main:
            inp1_edit.putpixel((i[0] - 16, i[1]), (0, 0, 0, 0))
        elif i in right_arm_main:
            inp1_edit.putpixel((i[0], i[1] + 16), (0, 0, 0, 0))
        elif i in right_leg_main:
            inp1_edit.putpixel((i[0], i[1] + 16), (0, 0, 0, 0))
    out = Image.alpha_composite(inp1_edit, inp2)
    return out
