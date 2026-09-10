"""Тесты приложения uniform: наложение изображений и поведение страницы."""

import base64
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from . import blockbench
from .composite import uniform_composite
from .constants import body_main, head_main
from .services import ImageProcessError, load_uniform

# Пара пикселей в областях головы/туловища (по uniform/constants.py).
HEAD_PX = (10, 10)
BODY_PX = (20, 20)


def png_bytes(image: Image.Image) -> bytes:
    """Сериализует изображение в PNG."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def make_skin(color=(120, 80, 200)) -> Image.Image:
    """Непрозрачный скин 64×64 одного цвета."""
    image = Image.new("RGBA", (64, 64), (*color, 255))
    return image


def make_uniform() -> Image.Image:
    """Форма 64×64 на прозрачном фоне с заливкой головы и туловища."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.putpixel(HEAD_PX, (255, 40, 40, 255))   # голова
    image.putpixel(BODY_PX, (40, 200, 80, 255))   # туловище
    return image


def uploaded(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="image/png")


class CompositeTests(TestCase):
    """Проверка ядра наложения (uniform/composite.py)."""

    def test_transparent_uniform_returns_skin_unchanged(self):
        skin = make_skin()
        uniform = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        result = uniform_composite(skin, uniform)
        self.assertEqual(list(result.getdata()), list(skin.convert("RGBA").getdata()))

    def test_uniform_is_painted_and_underlay_erased(self):
        self.assertIn(HEAD_PX, head_main)
        self.assertIn(BODY_PX, body_main)

        skin = make_skin()
        result = uniform_composite(skin, make_uniform())

        # Пиксели формы легли поверх скина.
        self.assertEqual(result.getpixel(HEAD_PX), (255, 40, 40, 255))
        self.assertEqual(result.getpixel(BODY_PX), (40, 200, 80, 255))

        # «Второй слой» скина под формой стёрт (прозрачен).
        self.assertEqual(result.getpixel((HEAD_PX[0] + 32, HEAD_PX[1]))[3], 0)
        self.assertEqual(result.getpixel((BODY_PX[0], BODY_PX[1] + 16))[3], 0)

        # Незатронутый пиксель остался прежним.
        self.assertEqual(result.getpixel((40, 40)), (120, 80, 200, 255))


class ServiceTests(TestCase):
    """Проверка валидации загружаемых файлов."""

    def test_load_uniform_requires_transparency(self):
        opaque = Image.new("RGB", (64, 64), (10, 10, 10))
        buf = io.BytesIO()
        opaque.save(buf, format="PNG")
        buf.seek(0)
        with self.assertRaises(ImageProcessError):
            load_uniform(buf)

    def test_load_uniform_accepts_rgba(self):
        buf = io.BytesIO()
        make_uniform().save(buf, format="PNG")
        buf.seek(0)
        self.assertEqual(load_uniform(buf).mode, "RGBA")


class BlockbenchProjectTests(TestCase):
    """Проект Blockbench, который открывается кнопкой «Редактировать»."""

    def test_project_embeds_skin_texture(self):
        """В проекте лежит скин как текстура, а не пустая заготовка."""
        png = png_bytes(make_skin())
        project = blockbench.build_project(png, (64, 64), name="uniform_applicator")

        self.assertEqual(project["meta"]["model_format"], "skin")
        self.assertTrue(project["meta"]["box_uv"])
        self.assertEqual(project["resolution"], {"width": 64, "height": 64})
        # Модель игрока Blockbench разворачивает сам по этому полю.
        self.assertEqual(project["skin_model"], "steve")

        prefix = "data:image/png;base64,"
        source = project["textures"][0]["source"]
        self.assertTrue(source.startswith(prefix))
        self.assertEqual(base64.b64decode(source[len(prefix):]), png)

    def test_editor_url_loads_project_as_json(self):
        """Ссылка ведёт в веб-приложение и несёт проект без потерь."""
        project = blockbench.build_project(png_bytes(make_skin()), (64, 64))
        url = blockbench.editor_url(project)

        self.assertTrue(url.startswith("https://web.blockbench.net/?"))
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["loadtype"], ["json"])
        self.assertEqual(query["loadname"], [blockbench.PROJECT_FILENAME])
        self.assertEqual(json.loads(query["loaddata"][0]), project)


@override_settings(DEBUG=True)
class PageTests(TestCase):
    """Поведение единственной страницы (GET/POST)."""

    def setUp(self):
        self._media = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._override = override_settings(MEDIA_ROOT=self._media.name)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        self._media.cleanup()

    def test_index_get_renders_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "uniform-form")
        self.assertContains(response, 'name="skin"')
        self.assertContains(response, 'name="uniform"')

    def test_post_without_files_returns_error(self):
        response = self.client.post("/", {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Загрузите скин и форму")

    def test_post_with_wrong_size_reports_error(self):
        small = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        response = self.client.post(
            "/",
            {
                "skin": uploaded("skin.png", png_bytes(make_skin())),
                "uniform": uploaded("uniform.png", png_bytes(small)),
            },
        )
        self.assertContains(response, "64×64")

    def test_post_with_opaque_uniform_reports_error(self):
        opaque = Image.new("RGB", (64, 64), (10, 10, 10))
        response = self.client.post(
            "/",
            {
                "skin": uploaded("skin.png", png_bytes(make_skin())),
                "uniform": uploaded("uniform.png", png_bytes(opaque)),
            },
        )
        self.assertContains(response, "прозрачн")

    def test_post_success_saves_and_serves_result(self):
        skin_bytes = png_bytes(make_skin())
        uniform_bytes = png_bytes(make_uniform())

        response = self.client.post(
            "/",
            {
                "skin": uploaded("skin.png", skin_bytes),
                "uniform": uploaded("uniform.png", uniform_bytes),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["url"].startswith("/media/processed/"))

        # Файл действительно сохранён и отдаётся как PNG.
        saved = Path(self._media.name) / "processed" / Path(payload["url"]).name
        self.assertTrue(saved.exists())
        result = self.client.get(payload["url"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Content-Type"], "image/png")
        body = b"".join(result.streaming_content)
        self.assertTrue(body.startswith(b"\x89PNG"))
        result.close()

        # Ссылка на веб-редактор Blockbench тоже вернулась.
        self.assertTrue(payload["blockbench"].startswith("/blockbench/"))

    def test_blockbench_redirect_opens_project_with_skin(self):
        """Кнопка «Редактировать в Blockbench Web» ведёт в редактор с нашим скином."""
        response = self.client.post(
            "/",
            {
                "skin": uploaded("skin.png", png_bytes(make_skin())),
                "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Blockbench")

        match = re.search(r'href="(/blockbench/[0-9a-f]{32}\.png/)"', response.content.decode())
        self.assertIsNotNone(match, "в результате нет ссылки на Blockbench")

        redirect = self.client.get(match.group(1))
        self.assertEqual(redirect.status_code, 302)
        location = redirect["Location"]
        self.assertTrue(location.startswith("https://web.blockbench.net/"))

        query = parse_qs(urlparse(location).query)
        self.assertEqual(query["loadtype"], ["json"])
        self.assertEqual(query["loadname"], ["uniform_applicator.bbmodel"])

        project = json.loads(query["loaddata"][0])
        self.assertEqual(project["meta"]["model_format"], "skin")
        self.assertEqual(project["skin_model"], "steve")

        # В редактор уезжает именно сохранённый результат, а не пустая заготовка.
        filename = match.group(1).rstrip("/").rsplit("/", 1)[-1]
        saved = Path(self._media.name) / "processed" / filename
        self.assertTrue(saved.is_file())

        prefix = "data:image/png;base64,"
        source = project["textures"][0]["source"]
        self.assertTrue(source.startswith(prefix))
        self.assertEqual(base64.b64decode(source[len(prefix):]), saved.read_bytes())

    def test_blockbench_rejects_foreign_filenames(self):
        self.assertEqual(self.client.get("/blockbench/passwd.png/").status_code, 404)
        self.assertEqual(self.client.get("/blockbench/" + "a" * 32 + ".png/").status_code, 404)
