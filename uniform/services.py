"""
Сервисный слой обработки изображений для одностраничника.

Отвечает за:
  * чтение и валидацию загруженных файлов (PNG 64×64);
  * наложение формы на скин (вызов uniform.composite.uniform_composite);
  * сохранение результата в media/processed/ и отдачу его URL.

Формат скина (classic/slim) влияет на наложение: у slim-скинов другая разметка
рук. Его можно задать в форме, но по умолчанию он определяется по самому скину
(``detect_skin_format``). Формат зашит в имя файла результата
(``<uuid>_<формат>.png``), чтобы маршрут ``/blockbench/<файл>/`` знал,
с какой моделью игрока открывать редактор.

Здесь удобно расширять логику: доп. валидации, форматы, пути сохранения.
"""

from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from . import skin_formats
from .composite import uniform_composite
from .constants import CLASSIC_ONLY_REGIONS

# Оба изображения — атлас скина 64×64 (как в Minecraft).
SIZE = (64, 64)

# Подкаталог внутри MEDIA_ROOT для результатов.
OUTPUT_SUBDIR = "processed"


class ImageProcessError(Exception):
    """Пользовательская ошибка валидации/обработки изображений."""


def load_skin(fileobj) -> Image.Image:
    """Читает файл скина: PNG 64×64 → RGBA."""
    return _load_png(fileobj, name="Скин").convert("RGBA")


def load_skin_bytes(data: bytes, *, name: str = "Скин игрока") -> Image.Image:
    """
    Читает скин из байтов — например, скачанный по нику игрока.

    Размеры HD-скинов (64×128, 128×128 и т.п.) кратны 64×64, а UV-разметка
    у них та же, поэтому такие скины уменьшаются до 64×64. Всё остальное —
    ошибка: разметка не совпадёт с формой (у старых скинов 64×32 левых рук и
    ног в текстуре просто нет).
    """
    image = _open_png(io.BytesIO(data), name=name)
    size = image.size

    if size == SIZE:
        return image.convert("RGBA")

    if size[0] % SIZE[0] == 0 and size[1] % SIZE[1] == 0:
        return image.convert("RGBA").resize(SIZE, Image.NEAREST)

    if size == (64, 32):
        raise ImageProcessError(
            f"«{name}»: старый формат скина 64×32 — в нём нет левых рук и ног, "
            "а форма рисуется в разметке 64×64. Нужен скин формата 64×64."
        )

    raise ImageProcessError(
        f"«{name}»: ожидается 64×64 (или кратный размер), а получено {size[0]}×{size[1]}."
    )


def to_data_url(image: Image.Image) -> str:
    """PNG-изображение → data-URL (для предпросмотра на странице)."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def load_uniform(fileobj) -> Image.Image:
    """Читает файл формы: PNG 64×64 с прозрачностью → RGBA."""
    image = _load_png(fileobj, name="Форма")
    if not _has_transparency(image):
        raise ImageProcessError(
            "«Форма»: нужен PNG с прозрачностью — рисуйте форму на прозрачном фоне."
        )
    return image.convert("RGBA")


def compose(skin: Image.Image, uniform: Image.Image,
            skin_format: str = skin_formats.DEFAULT) -> Image.Image:
    """Накладывает форму на скин (разметка рук зависит от формата)."""
    return uniform_composite(skin, uniform, skin_format)


def detect_skin_format(image: Image.Image) -> str:
    """
    Определяет формат скина по самой картинке.

    В текстуре есть области, которые нужны только classic-скину: у slim руки
    на пиксель уже, и эти пиксели не используются (``CLASSIC_ONLY_REGIONS``).
    Если в каждой такой области закрашены все пиксели — скин classic, иначе slim.

    Закрашенным считается пиксель, который не полностью прозрачный.
    """
    rgba = image.convert("RGBA")

    for x1, y1, x2, y2 in CLASSIC_ONLY_REGIONS:
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                if rgba.getpixel((x, y))[3] == 0:
                    return skin_formats.SLIM

    return skin_formats.CLASSIC


def save_result(image: Image.Image, skin_format: str = skin_formats.DEFAULT) -> str:
    """
    Сохраняет результат в media/processed/<uuid>_<формат>.png.

    Возвращает относительный URL файла (например 'media/processed/ab12_classic.png').
    Формат — часть имени файла, поэтому он проверяется: имя должно оставаться
    таким, каким его ждёт маршрут /blockbench/<файл>/.
    """
    if not skin_formats.is_valid(skin_format):
        raise ValueError(f"Неизвестный формат скина: {skin_format!r}")

    out_dir = Path(settings.MEDIA_ROOT) / OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}_{skin_format}.png"
    image.save(out_dir / filename, format="PNG")

    return f"{settings.MEDIA_URL}{OUTPUT_SUBDIR}/{filename}"


def _open_png(fileobj, *, name: str) -> Image.Image:
    """Открывает файл и проверяет, что это корректный PNG (размер не проверяет)."""
    try:
        fileobj.seek(0)
        image = Image.open(fileobj)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageProcessError(f"«{name}»: файл не является корректным изображением.")

    if image.format != "PNG":
        raise ImageProcessError(f"«{name}»: поддерживается только PNG.")

    return image


def _load_png(fileobj, *, name: str) -> Image.Image:
    """Открывает загруженный файл и требует ровно 64×64."""
    image = _open_png(fileobj, name=name)

    if image.size != SIZE:
        raise ImageProcessError(
            f"«{name}»: ожидается размер 64×64, а получено {image.size[0]}×{image.size[1]}."
        )

    return image


def _has_transparency(image: Image.Image) -> bool:
    """True, если в изображении есть альфа-канал или метка прозрачности."""
    if "A" in image.mode:
        return True
    return "transparency" in image.info
