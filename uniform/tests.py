"""Тесты приложения uniform: наложение изображений и поведение страницы."""

import base64
import io
import json
import os
import re
import tempfile
import time
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from . import blockbench, media_cleanup, minecraft_profile, skin_formats
from .composite import uniform_composite
from .constants import (
    ARM_MAIN,
    CLASSIC_ONLY_REGIONS,
    body_main,
    box_uv_cells,
    head_main,
    left_arm_main,
    left_leg_main,
    right_arm_main,
    right_leg_main,
)
from .services import (
    ImageProcessError,
    detect_skin_format,
    load_skin_bytes,
    load_uniform,
)

# Пара пикселей в областях головы/туловища (по uniform/constants.py).
HEAD_PX = (10, 10)
BODY_PX = (20, 20)

# Рука: пиксель, который есть и у classic, и у slim (передняя грань правой руки),
# и пиксель, который у slim не используется (правый край classic-разметки).
ARM_BOTH_PX = (52, 25)
ARM_CLASSIC_ONLY_PX = (54, 25)
#: Куда попадает стираемый второй слой (рукав) для этих пикселей.
ARM_LAYER_OFFSET_Y = 16


def png_bytes(image: Image.Image) -> bytes:
    """Сериализует изображение в PNG."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def make_skin(color=(120, 80, 200)) -> Image.Image:
    """Непрозрачный скин 64×64 одного цвета."""
    image = Image.new("RGBA", (64, 64), (*color, 255))
    return image


def make_slim_skin(color=(120, 80, 200)) -> Image.Image:
    """Скин 64×64, у которого области classic-скина прозрачны (значит slim)."""
    image = make_skin(color)
    for x1, y1, x2, y2 in CLASSIC_ONLY_REGIONS:
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                image.putpixel((x, y), (0, 0, 0, 0))
    return image


def make_uniform() -> Image.Image:
    """Форма 64×64 на прозрачном фоне с заливкой головы и туловища."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.putpixel(HEAD_PX, (255, 40, 40, 255))   # голова
    image.putpixel(BODY_PX, (40, 200, 80, 255))   # туловище
    return image


def uploaded(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="image/png")


def textures_value(skin_url: str, model: str | None = None) -> str:
    """Свойство textures профиля Mojang: ссылка на скин + модель (slim/classic)."""
    skin = {"url": skin_url}
    if model:
        skin["metadata"] = {"model": model}
    payload = {"textures": {"SKIN": skin}}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def fake_mojang(skin_png: bytes, *, model: str | None = None, nickname: str = "Notch",
                uuid: str = "069a79f444e94726a5befca90e38aaf5"):
    """
    Подменяет HTTP-слой Mojang: ник → UUID → профиль → PNG скина.

    Возвращает мок ``_request``, чтобы тесты могли проверить число запросов.
    """
    skin_url = "http://textures.minecraft.net/texture/" + "a" * 64

    def fake_request(url, *_args, **_kwargs):
        if "lookup/name/" in url or "users/profiles/minecraft/" in url:
            return json.dumps({"id": uuid, "name": nickname}).encode("utf-8")
        if "sessionserver.mojang.com" in url:
            profile = {"id": uuid, "name": nickname,
                       "properties": [{"name": "textures",
                                       "value": textures_value(skin_url, model)}]}
            return json.dumps(profile).encode("utf-8")
        if url == skin_url.replace("http://", "https://"):
            return skin_png
        raise AssertionError(f"неожиданный запрос: {url}")

    return mock.patch.object(minecraft_profile, "_request", side_effect=fake_request)


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


class SkinFormatTests(TestCase):
    """Разметка форматов classic/slim и её влияние на наложение формы."""

    def test_classic_only_regions_are_classic_arm_cells(self):
        """
        Области автоопределения — это пиксели, которые есть только у classic.

        Иначе правило «закрашены все области → classic» ломается: тест следит,
        чтобы эти ячейки входили в classic-разметку рук и не входили в slim.
        """
        classic = set(ARM_MAIN[skin_formats.CLASSIC][0]) | set(ARM_MAIN[skin_formats.CLASSIC][1])
        slim = set(ARM_MAIN[skin_formats.SLIM][0]) | set(ARM_MAIN[skin_formats.SLIM][1])

        cells = [
            (x, y)
            for x1, y1, x2, y2 in CLASSIC_ONLY_REGIONS
            for x in range(x1, x2 + 1)
            for y in range(y1, y2 + 1)
        ]

        self.assertTrue(cells)
        self.assertEqual(set(cells) - classic, set(), "области выходят за classic-разметку рук")
        self.assertEqual(set(cells) & slim, set(), "области используются и у slim")

    def test_box_uv_cells_matches_existing_constants(self):
        """Генератор ячеек описывает ровно те же области, что и списки в constants.py."""
        parts = [
            (head_main, (0, 0, 8, 8, 8)),
            (body_main, (16, 16, 8, 12, 4)),
            (right_arm_main, (40, 16, 4, 12, 4)),
            (left_arm_main, (32, 48, 4, 12, 4)),
            (right_leg_main, (0, 16, 4, 12, 4)),
            (left_leg_main, (16, 48, 4, 12, 4)),
        ]
        for cells, args in parts:
            with self.subTest(args=args):
                self.assertEqual(set(cells), set(box_uv_cells(*args)))

    def test_slim_arms_are_narrower_than_classic(self):
        """У slim руки на пиксель уже, и часть classic-разметки в slim не попадает."""
        classic_right, classic_left = ARM_MAIN[skin_formats.CLASSIC]
        slim_right, slim_left = ARM_MAIN[skin_formats.SLIM]

        # Общая часть разметки (передняя грань руки) есть в обоих форматах.
        self.assertIn(ARM_BOTH_PX, classic_right)
        self.assertIn(ARM_BOTH_PX, slim_right)

        # Правый край classic-руки у slim уже не используется.
        self.assertIn(ARM_CLASSIC_ONLY_PX, classic_right)
        self.assertNotIn(ARM_CLASSIC_ONLY_PX, slim_right)
        self.assertNotIn((46, 52), slim_left)  # то же для левой руки
        self.assertIn((46, 52), classic_left)

        # У slim те же грани, но уже: область меньше по площади.
        self.assertLess(len(slim_right), len(classic_right))
        self.assertLess(len(slim_left), len(classic_left))

    def test_classic_erases_sleeve_outside_slim_layout(self):
        """На classic пиксель у края руки стирает рукав, на slim — нет."""
        uniform = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        uniform.putpixel(ARM_CLASSIC_ONLY_PX, (10, 200, 10, 255))
        skin = make_skin()
        layer_px = (ARM_CLASSIC_ONLY_PX[0], ARM_CLASSIC_ONLY_PX[1] + ARM_LAYER_OFFSET_Y)

        classic = uniform_composite(skin, uniform, skin_formats.CLASSIC)
        slim = uniform_composite(skin, uniform, skin_formats.SLIM)

        self.assertEqual(classic.getpixel(layer_px)[3], 0)
        self.assertEqual(slim.getpixel(layer_px), (120, 80, 200, 255))

    def test_both_formats_erase_sleeve_inside_their_layout(self):
        """Пиксель в общей части разметки стирает рукав у обоих форматов."""
        uniform = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        uniform.putpixel(ARM_BOTH_PX, (10, 200, 10, 255))
        skin = make_skin()
        layer_px = (ARM_BOTH_PX[0], ARM_BOTH_PX[1] + ARM_LAYER_OFFSET_Y)

        for skin_format in skin_formats.ALL:
            with self.subTest(skin_format=skin_format):
                result = uniform_composite(skin, uniform, skin_format)
                self.assertEqual(result.getpixel(layer_px)[3], 0)
                self.assertEqual(result.getpixel(ARM_BOTH_PX), (10, 200, 10, 255))

    def test_unknown_format_is_rejected(self):
        uniform = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        with self.assertRaises(ValueError):
            uniform_composite(make_skin(), uniform, "wide")


class DetectSkinFormatTests(TestCase):
    """Автоопределение формата скина по картинке (services.detect_skin_format)."""

    def test_fully_painted_skin_is_classic(self):
        self.assertEqual(detect_skin_format(make_skin()), skin_formats.CLASSIC)

    def test_skin_with_empty_classic_regions_is_slim(self):
        self.assertEqual(detect_skin_format(make_slim_skin()), skin_formats.SLIM)

    def test_one_empty_classic_region_is_enough_for_slim(self):
        """Достаточно одной незакрашенной области из четырёх, чтобы это был slim."""
        for index, (x1, y1, x2, y2) in enumerate(CLASSIC_ONLY_REGIONS):
            with self.subTest(region=(x1, y1, x2, y2)):
                skin = make_skin()
                for x in range(x1, x2 + 1):
                    for y in range(y1, y2 + 1):
                        skin.putpixel((x, y), (0, 0, 0, 0))
                self.assertEqual(detect_skin_format(skin), skin_formats.SLIM)

    def test_fully_transparent_skin_is_slim(self):
        transparent = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        self.assertEqual(detect_skin_format(transparent), skin_formats.SLIM)

    def test_pixels_outside_regions_do_not_matter(self):
        """Важны только четыре области: остальное на формат не влияет."""
        skin = make_skin()
        for x1, y1, x2, y2 in CLASSIC_ONLY_REGIONS:
            for x in range(x1, x2 + 1):
                for y in range(y1, y2 + 1):
                    skin.putpixel((x, y), (0, 0, 0, 0))
        # Закрашиваем всё, кроме этих областей — вывод не меняется.
        self.assertEqual(detect_skin_format(skin), skin_formats.SLIM)

        skin2 = make_slim_skin()
        for x in range(64):
            for y in range(64):
                if skin2.getpixel((x, y))[3] == 0:
                    skin2.putpixel((x, y), (10, 20, 30, 1))  # почти прозрачный, но закрашен
        self.assertEqual(detect_skin_format(skin2), skin_formats.CLASSIC)


class MinecraftProfileTests(TestCase):
    """Скин игрока по нику (uniform/minecraft_profile.py) — HTTP подменяется."""

    def setUp(self):
        minecraft_profile.clear_cache()
        self.addCleanup(minecraft_profile.clear_cache)
        self.png = png_bytes(make_skin())

    def test_nickname_is_validated_before_any_request(self):
        """Некорректный ник не доходит до сети."""
        with mock.patch.object(minecraft_profile, "_request") as request:
            for nickname in ("", "  ", "bad nick", "никик", "a" * 17, "nick!"):
                with self.subTest(nickname=nickname):
                    with self.assertRaises(minecraft_profile.ProfileError):
                        minecraft_profile.fetch_skin(nickname)
            request.assert_not_called()

    def test_skin_and_format_come_from_mojang(self):
        """slim-скин определяется по metadata.model, иначе classic."""
        cases = [("slim", skin_formats.SLIM), (None, skin_formats.CLASSIC), ("classic", skin_formats.CLASSIC)]

        for model, expected in cases:
            with self.subTest(model=model):
                minecraft_profile.clear_cache()
                with fake_mojang(self.png, model=model):
                    profile = minecraft_profile.fetch_skin("Notch")
                self.assertEqual(profile.nickname, "Notch")
                self.assertEqual(profile.uuid, "069a79f444e94726a5befca90e38aaf5")
                self.assertEqual(profile.skin_format, expected)
                self.assertEqual(profile.skin_png, self.png)

    def test_unknown_player_reports_friendly_error(self):
        error = minecraft_profile._HttpError("not_found")
        with mock.patch.object(minecraft_profile, "_request", side_effect=error):
            with self.assertRaises(minecraft_profile.ProfileError) as ctx:
                minecraft_profile.fetch_skin("NoSuchPlayer")
        self.assertIn("не найден", str(ctx.exception))
        self.assertIn("NoSuchPlayer", str(ctx.exception))

    def test_network_problems_are_reported(self):
        for kind, expected in (("network", "связаться"), ("rate_limited", "частоту"), ("server", "ошибкой")):
            with self.subTest(kind=kind):
                minecraft_profile.clear_cache()
                error = minecraft_profile._HttpError(kind)
                with mock.patch.object(minecraft_profile, "_request", side_effect=error):
                    with self.assertRaises(minecraft_profile.ProfileError) as ctx:
                        minecraft_profile.fetch_skin("Notch")
                self.assertIn(expected, str(ctx.exception))

    def test_second_lookup_uses_cache(self):
        """Предпросмотр и отправка формы не дёргают Mojang дважды."""
        with fake_mojang(self.png) as request:
            minecraft_profile.fetch_skin("Notch")
            calls = request.call_count
            minecraft_profile.fetch_skin("notch")  # регистр не важен
            self.assertEqual(request.call_count, calls)

    def test_skin_without_textures_is_reported(self):
        profile = {"id": "x", "name": "Notch", "properties": []}
        with mock.patch.object(minecraft_profile, "_request",
                               return_value=json.dumps(profile).encode("utf-8")):
            with self.assertRaises(minecraft_profile.ProfileError):
                minecraft_profile.fetch_skin("Notch")


class FetchedSkinTests(TestCase):
    """Проверка скинов, полученных по нику (uniform/services.load_skin_bytes)."""

    def test_hd_skin_is_scaled_down_to_64(self):
        hd = Image.new("RGBA", (128, 128), (200, 30, 30, 255))
        image = load_skin_bytes(png_bytes(hd), name="Скин игрока Notch")
        self.assertEqual(image.size, (64, 64))
        self.assertEqual(image.getpixel((5, 5)), (200, 30, 30, 255))

    def test_legacy_64x32_skin_is_rejected_with_reason(self):
        """Старый формат 64×32 не совпадает с разметкой формы — говорим об этом."""
        legacy = Image.new("RGBA", (64, 32), (10, 10, 10, 255))
        with self.assertRaises(ImageProcessError) as ctx:
            load_skin_bytes(png_bytes(legacy), name="Скин игрока jeb_")
        self.assertIn("64×32", str(ctx.exception))
        self.assertIn("64×64", str(ctx.exception))

    def test_not_a_png_is_rejected(self):
        with self.assertRaises(ImageProcessError):
            load_skin_bytes(b"<html>not a png</html>", name="Скин игрока Notch")


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


class MediaCleanupTests(TestCase):
    """Автоочистка media: удаление устаревших результатов (uniform/media_cleanup.py)."""

    def setUp(self):
        self._media = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._override = override_settings(MEDIA_ROOT=self._media.name)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(self._media.cleanup)
        media_cleanup.stop_scheduler()
        self.addCleanup(media_cleanup.stop_scheduler)
        media_cleanup._last_run = 0
        self.addCleanup(setattr, media_cleanup, "_last_run", 0)

    def _file(self, name: str, *, age: float = 0, subdir: str = "processed") -> Path:
        """Создаёт файл с заданным «возрастом» (в секундах)."""
        path = Path(self._media.name) / subdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_removes_only_expired_files(self):
        old = self._file("old_classic.png", age=3600)
        fresh = self._file("fresh_classic.png", age=10)

        report = media_cleanup.cleanup(max_age=1800)

        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(report["deleted"], 1)
        self.assertEqual(report["bytes"], 10)

    def test_max_age_zero_removes_everything(self):
        files = [self._file(f"{i}_slim.png", age=1) for i in range(3)]
        report = media_cleanup.cleanup(max_age=0)

        self.assertEqual(report["deleted"], 3)
        self.assertTrue(all(not path.exists() for path in files))

    def test_empty_subdirectories_are_removed_but_media_root_stays(self):
        self._file("x_classic.png", age=3600)
        media_cleanup.cleanup(max_age=1800)
        self.assertTrue(Path(self._media.name).is_dir())
        self.assertFalse((Path(self._media.name) / "processed").exists())

    def test_service_files_are_kept(self):
        """.gitkeep и прочие файлы с точкой не трогаем."""
        keep = self._file(".gitkeep", age=3600)
        media_cleanup.cleanup(max_age=0)
        self.assertTrue(keep.exists())

    def test_missing_media_dir_is_not_an_error(self):
        with override_settings(MEDIA_ROOT=str(Path(self._media.name) / "nope")):
            report = media_cleanup.cleanup(max_age=0)
        self.assertEqual(report, {"deleted": 0, "bytes": 0, "dirs": 0, "errors": 0})

    @override_settings(MEDIA_CLEANUP_MAX_AGE=1800)
    def test_age_comes_from_settings_by_default(self):
        old = self._file("old_classic.png", age=3600)
        fresh = self._file("fresh_classic.png", age=10)
        media_cleanup.cleanup()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    @override_settings(MEDIA_CLEANUP_INTERVAL=1800)
    def test_run_if_due_waits_for_interval(self):
        old = self._file("one_classic.png", age=3600)

        first = media_cleanup.run_if_due(now=10_000)
        self.assertIsNotNone(first)
        self.assertFalse(old.exists())

        self._file("two_classic.png", age=3600)
        second = media_cleanup.run_if_due(now=10_000 + 60)      # прошла минута
        self.assertIsNone(second, "уборка не должна идти чаще интервала")
        self.assertTrue((Path(self._media.name) / "processed" / "two_classic.png").exists())

        third = media_cleanup.run_if_due(now=10_000 + 1800)     # прошёл интервал
        self.assertIsNotNone(third)

    def test_scheduler_starts_single_background_thread(self):
        with mock.patch.object(media_cleanup, "cleanup", return_value={}) as cleanup:
            first = media_cleanup.start_scheduler()
            second = media_cleanup.start_scheduler()
            self.assertIs(first, second)
            self.assertTrue(first.daemon)

            # Поток делает первую уборку сразу после запуска.
            for _ in range(50):
                if cleanup.called:
                    break
                time.sleep(0.02)
            self.assertTrue(cleanup.called, "фоновый поток не сделал первую уборку")

    @override_settings(MEDIA_CLEANUP_ENABLED=False)
    def test_scheduler_can_be_disabled(self):
        self.assertIsNone(media_cleanup.start_scheduler())

    def test_clean_media_command(self):
        old = self._file("old_classic.png", age=7200)
        fresh = self._file("fresh_classic.png", age=5)

        media_cleanup.cleanup()          # по настройкам: старше 30 минут
        call_command("clean_media", "--all", stdout=io.StringIO())

        self.assertFalse(old.exists())
        self.assertFalse(fresh.exists())


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

    def test_project_model_matches_skin_format(self):
        """classic открывается моделью Steve, slim — моделью Alex."""
        png = png_bytes(make_skin())

        for skin_format, expected_model in (
            (skin_formats.CLASSIC, "steve"),
            (skin_formats.SLIM, "alex.java"),
        ):
            with self.subTest(skin_format=skin_format):
                project = blockbench.build_project(
                    png, (64, 64), model=blockbench.SKIN_MODELS[skin_format]
                )
                self.assertEqual(project["skin_model"], expected_model)

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
        minecraft_profile.clear_cache()
        self.addCleanup(minecraft_profile.clear_cache)

    def tearDown(self):
        self._override.disable()
        self._media.cleanup()

    def test_index_get_renders_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "uniform-form")
        self.assertContains(response, 'name="skin"')
        self.assertContains(response, 'name="uniform"')
        # Шаг 1 — выбор формата скина, до загрузки файлов.
        self.assertContains(response, 'name="skin_format"')
        self.assertContains(response, 'value="classic"')
        self.assertContains(response, 'value="slim"')
        self.assertNotContains(response, "checked")  # формат выбирает пользователь
        # Заголовок шага — обычный блок внутри карточки: <legend> рисуется на рамке
        # и «прорезает» её, поэтому его тут быть не должно.
        html = response.content.decode()
        self.assertContains(response, 'class="format-legend"')
        self.assertNotContains(response, "<legend")
        self.assertLess(html.index('class="format-legend"'), html.index('class="format-options"'))
        # Шаг 2 — скин можно дать ником игрока.
        self.assertContains(response, 'name="nickname"')
        self.assertContains(response, 'id="nick-btn"')
        # Подтверждённый ник, отдельно от поля ввода.
        self.assertContains(response, 'name="skin_nickname"')
        # Строка поиска по нику — над блоками скина и формы, одной широкой строкой.
        self.assertLess(html.index('id="nick-skin"'), html.index('class="upload-grid"'))
        # Предпросмотр скина один: и файл, и ник показываются в блоке «2. Скин».
        self.assertContains(response, 'id="preview-skin"')
        self.assertNotContains(response, 'preview-nick')
        # Шаблон адреса для app.js: подставляется ник вместо NICKNAME.
        self.assertContains(response, 'data-lookup-url="/skin/NICKNAME/"')

    def test_skin_by_nickname_returns_skin_and_format(self):
        """Предпросмотр по нику: скин в data-URL + определённый формат."""
        with fake_mojang(png_bytes(make_skin()), model="slim", nickname="Alex"):
            response = self.client.get("/skin/Alex/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["nickname"], "Alex")
        self.assertEqual(payload["format"], skin_formats.SLIM)
        self.assertIn("Slim", payload["format_label"])

        prefix = "data:image/png;base64,"
        self.assertTrue(payload["skin"].startswith(prefix))
        image = Image.open(io.BytesIO(base64.b64decode(payload["skin"][len(prefix):])))
        self.assertEqual(image.size, (64, 64))

    def test_skin_by_nickname_reports_bad_nickname(self):
        response = self.client.get("/skin/bad%20nick/")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("Ник", response.json()["error"])

    def test_skin_by_nickname_reports_unknown_player(self):
        error = minecraft_profile._HttpError("not_found")
        with mock.patch.object(minecraft_profile, "_request", side_effect=error):
            response = self.client.get("/skin/NoSuchPlayer/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("не найден", response.json()["error"])

    def test_skin_by_nickname_rejects_other_methods(self):
        self.assertEqual(self.client.post("/skin/Notch/").status_code, 405)

    def test_post_by_nickname_uses_format_from_mojang(self):
        """Скин по нику: формат берём у Mojang, а не из формы."""
        uniform = png_bytes(make_uniform())
        with fake_mojang(png_bytes(make_skin()), model="slim", nickname="Alex"):
            response = self.client.post(
                "/",
                # Пользователь выбрал classic, но у игрока скин slim.
                {"skin_format": skin_formats.CLASSIC, "nickname": "Alex",
                 "uniform": uploaded("uniform.png", uniform)},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["skin_source"], "nickname")
        self.assertEqual(payload["format"], skin_formats.SLIM)
        self.assertTrue(payload["file"].endswith("_slim.png"))
        self.assertIn("Alex", payload["nickname"])
        # Пользователя предупреждаем, что формат взяли не тот, что он выбрал.
        self.assertIn("Slim", payload["format_note"])
        self.assertTrue((Path(self._media.name) / "processed" / payload["file"]).is_file())

    def test_post_by_nickname_without_format_choice(self):
        """Ник — единственный источник скина: формат выбирать не обязательно."""
        with fake_mojang(png_bytes(make_skin()), nickname="Notch"):
            response = self.client.post(
                "/",
                {"nickname": "Notch", "uniform": uploaded("uniform.png", png_bytes(make_uniform()))},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["format"], skin_formats.CLASSIC)
        self.assertEqual(payload["format_note"], "")

    def test_post_uses_confirmed_nickname_when_field_is_empty(self):
        """
        Найденный скин не теряется, если поле ника опустело.

        Регрессия: раньше состояние скина жило только в тексте поля, и пустое
        поле давало «Загрузите скин файлом или впишите ник игрока», хотя скин
        был найден (и его предпросмотр висел на странице).
        """
        with fake_mojang(png_bytes(make_skin()), model="slim", nickname="Alex"):
            response = self.client.post(
                "/",
                {"skin_nickname": "Alex", "nickname": "",
                 "uniform": uploaded("uniform.png", png_bytes(make_uniform()))},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["skin_source"], "nickname")
        self.assertEqual(payload["nickname"], "Alex")
        self.assertEqual(payload["format"], skin_formats.SLIM)

    def test_confirmed_nickname_wins_over_edited_text(self):
        """Если поле переписали, а скин не переискали — берём подтверждённый ник."""
        with fake_mojang(png_bytes(make_skin()), nickname="Technoblade") as request:
            response = self.client.post(
                "/",
                {"skin_nickname": "Technoblade", "nickname": "SomeoneElse",
                 "uniform": uploaded("uniform.png", png_bytes(make_uniform()))},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["nickname"], "Technoblade")
        for call in request.call_args_list:
            self.assertNotIn("SomeoneElse", call.args[0])

    def test_post_without_skin_at_all_asks_for_it(self):
        response = self.client.post(
            "/",
            {"skin_format": skin_formats.CLASSIC,
             "uniform": uploaded("uniform.png", png_bytes(make_uniform()))},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("скин", response.json()["error"])

    def test_post_with_file_does_not_touch_mojang(self):
        """Если скин дан файлом, ник игнорируется и в сеть не ходим."""
        with mock.patch.object(minecraft_profile, "_request") as request:
            response = self.client.post(
                "/",
                {"skin_format": skin_formats.CLASSIC,
                 "nickname": "Notch",
                 "skin": uploaded("skin.png", png_bytes(make_skin())),
                 "uniform": uploaded("uniform.png", png_bytes(make_uniform()))},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["skin_source"], "file")
        request.assert_not_called()

    def test_post_without_format_uses_detected_format(self):
        """Формат можно не выбирать: он определяется по самому скину."""
        cases = [
            (make_skin(), skin_formats.CLASSIC),
            (make_slim_skin(), skin_formats.SLIM),
        ]
        for image, expected in cases:
            with self.subTest(expected=expected):
                response = self.client.post(
                    "/",
                    {
                        "skin": uploaded("skin.png", png_bytes(image)),
                        "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
                    },
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertEqual(response.status_code, 200, response.content)
                payload = response.json()
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["format"], expected)
                self.assertTrue(payload["file"].endswith(f"_{expected}.png"))
                self.assertEqual(payload["format_note"], "")

    def test_manual_format_choice_wins_over_detection(self):
        """Если формат выбрали вручную, он главнее автоопределения — с пояснением."""
        slim_image = make_slim_skin()
        response = self.client.post(
            "/",
            {
                "skin_format": skin_formats.CLASSIC,   # выбрано вручную
                "skin": uploaded("skin.png", png_bytes(slim_image)),
                "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["format"], skin_formats.CLASSIC)
        self.assertTrue(payload["file"].endswith("_classic.png"))
        self.assertIn("Slim", payload["format_note"])
        self.assertIn("Classic", payload["format_note"])

    def test_detected_format_used_when_choice_matches(self):
        """Совпадающий выбор — это не «ручной override», пояснение не нужно."""
        response = self.client.post(
            "/",
            {
                "skin_format": skin_formats.SLIM,
                "skin": uploaded("skin.png", png_bytes(make_slim_skin())),
                "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = response.json()
        self.assertEqual(payload["format"], skin_formats.SLIM)
        self.assertEqual(payload["format_note"], "")

    def test_unknown_format_value_is_ignored(self):
        """Непонятное значение формата не ошибка: работает автоопределение."""
        response = self.client.post(
            "/",
            {
                "skin_format": "wide",
                "skin": uploaded("skin.png", png_bytes(make_slim_skin())),
                "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["format"], skin_formats.SLIM)
        self.assertEqual(payload["format_note"], "")

    def test_post_without_files_returns_error(self):
        response = self.client.post("/", {"skin_format": skin_formats.CLASSIC})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Загрузите скин")

    def test_post_with_wrong_size_reports_error(self):
        small = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        response = self.client.post(
            "/",
            {
                "skin_format": skin_formats.SLIM,
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
                "skin_format": skin_formats.CLASSIC,
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
                "skin_format": skin_formats.SLIM,
                "skin": uploaded("skin.png", skin_bytes),
                "uniform": uploaded("uniform.png", uniform_bytes),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["url"].startswith("/media/processed/"))
        # Формат уезжает и в ответ, и в имя файла результата.
        self.assertEqual(payload["format"], skin_formats.SLIM)
        self.assertTrue(payload["file"].endswith("_slim.png"), payload["file"])
        self.assertIn("Slim", payload["format_label"])

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

    def test_result_depends_on_skin_format(self):
        """Один и тот же ввод даёт разный результат для classic и slim."""
        uniform = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        uniform.putpixel(ARM_CLASSIC_ONLY_PX, (10, 200, 10, 255))  # есть только в classic-разметке
        layer_px = (ARM_CLASSIC_ONLY_PX[0], ARM_CLASSIC_ONLY_PX[1] + ARM_LAYER_OFFSET_Y)

        results = {}
        for skin_format in skin_formats.ALL:
            response = self.client.post(
                "/",
                {
                    "skin_format": skin_format,
                    "skin": uploaded("skin.png", png_bytes(make_skin())),
                    "uniform": uploaded("uniform.png", png_bytes(uniform)),
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            self.assertEqual(response.status_code, 200, response.content)
            payload = response.json()
            results[skin_format] = Image.open(
                Path(self._media.name) / "processed" / payload["file"]
            ).convert("RGBA")

        # classic стирает рукав под формой, slim этот пиксель не считает рукой.
        self.assertEqual(results[skin_formats.CLASSIC].getpixel(layer_px)[3], 0)
        self.assertEqual(
            results[skin_formats.SLIM].getpixel(layer_px), (120, 80, 200, 255)
        )

    def test_blockbench_redirect_opens_project_with_skin(self):
        """Кнопка «Редактировать в Blockbench Web» ведёт в редактор с нашим скином."""
        for skin_format, expected_model in (
            (skin_formats.CLASSIC, "steve"),
            (skin_formats.SLIM, "alex.java"),
        ):
            with self.subTest(skin_format=skin_format):
                self._assert_blockbench_redirect(skin_format, expected_model)

    def _assert_blockbench_redirect(self, skin_format, expected_model):
        response = self.client.post(
            "/",
            {
                "skin_format": skin_format,
                "skin": uploaded("skin.png", png_bytes(make_skin())),
                "uniform": uploaded("uniform.png", png_bytes(make_uniform())),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Blockbench")

        pattern = rf'href="(/blockbench/[0-9a-f]{{32}}_{skin_format}\.png/)"'
        match = re.search(pattern, response.content.decode())
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
        # Модель игрока зависит от формата скина.
        self.assertEqual(project["skin_model"], expected_model)

        # В редактор уезжает именно сохранённый результат, а не пустая заготовка.
        filename = match.group(1).rstrip("/").rsplit("/", 1)[-1]
        saved = Path(self._media.name) / "processed" / filename
        self.assertTrue(saved.is_file())

        prefix = "data:image/png;base64,"
        source = project["textures"][0]["source"]
        self.assertTrue(source.startswith(prefix))
        self.assertEqual(base64.b64decode(source[len(prefix):]), saved.read_bytes())

    def test_blockbench_rejects_foreign_filenames(self):
        """Маршрут отдаёт только свои файлы результатов: uuid + известный формат."""
        uuid = "a" * 32
        for filename in (
            "passwd.png",
            f"{uuid}.png",            # старый формат без суффикса
            f"{uuid}_wide.png",       # неизвестный формат
            f"../{uuid}_slim.png",    # попытка выйти из каталога
        ):
            with self.subTest(filename=filename):
                response = self.client.get(f"/blockbench/{filename}/")
                self.assertEqual(response.status_code, 404)

        # А известный формат без файла на диске — тоже 404, но уже по другой причине.
        self.assertEqual(self.client.get(f"/blockbench/{uuid}_slim.png/").status_code, 404)
