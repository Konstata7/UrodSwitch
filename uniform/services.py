"""
Сервисный слой обработки изображений для одностраничника.

Отвечает за:
  * чтение и валидацию загруженных файлов (PNG 64×64);
  * наложение формы на скин (вызов uniform.composite.uniform_composite);
  * сохранение результата в media/processed/ и отдачу его URL.

Здесь удобно расширять логику: доп. валидации, форматы, пути сохранения.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from .composite import uniform_composite

# Оба изображения — атлас скина 64×64 (как в Minecraft).
SIZE = (64, 64)

# Подкаталог внутри MEDIA_ROOT для результатов.
OUTPUT_SUBDIR = "processed"


class ImageProcessError(Exception):
    """Пользовательская ошибка валидации/обработки изображений."""


def load_skin(fileobj) -> Image.Image:
    """Читает файл скина: PNG 64×64 → RGBA."""
    return _load_png(fileobj, name="Скин").convert("RGBA")


def load_uniform(fileobj) -> Image.Image:
    """Читает файл формы: PNG 64×64 с прозрачностью → RGBA."""
    image = _load_png(fileobj, name="Форма")
    if not _has_transparency(image):
        raise ImageProcessError(
            "«Форма»: нужен PNG с прозрачностью — рисуйте форму на прозрачном фоне."
        )
    return image.convert("RGBA")


def compose(skin: Image.Image, uniform: Image.Image) -> Image.Image:
    """Накладывает форму на скин и возвращает итоговое изображение."""
    return uniform_composite(skin, uniform)


def save_result(image: Image.Image) -> str:
    """
    Сохраняет результат в media/processed/<uuid>.png.

    Возвращает относительный URL файла (например 'media/processed/ab12.png').
    """
    out_dir = Path(settings.MEDIA_ROOT) / OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.png"
    image.save(out_dir / filename, format="PNG")

    return f"{settings.MEDIA_URL}{OUTPUT_SUBDIR}/{filename}"


def _load_png(fileobj, *, name: str) -> Image.Image:
    """Открывает загруженный файл и проверяет базовые требования."""
    try:
        fileobj.seek(0)
        image = Image.open(fileobj)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageProcessError(f"«{name}»: файл не является корректным изображением.")

    if image.format != "PNG":
        raise ImageProcessError(f"«{name}»: поддерживается только PNG.")

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
