"""
Разовая уборка каталога media — для cron или Планировщика задач Windows.

Примеры:

    # вручную: удалить из media всё старше получаса (настройка MEDIA_CLEANUP_MAX_AGE)
    python manage.py clean_media

    # удалить всё, не глядя на возраст
    python manage.py clean_media --all

    # удалить файлы старше часа
    python manage.py clean_media --max-age 3600

    # cron: каждые 30 минут
    */30 * * * * cd /path/to/project && .venv/bin/python manage.py clean_media --quiet

Обычно эта команда не нужна: в процессе веб-сервера уже работает фоновый поток
уборки (см. ``uniform/media_cleanup.py``). Команда пригодится, если поток
отключён (``DJANGO_MEDIA_CLEANUP=0``) или воркеров несколько.
"""

from django.core.management.base import BaseCommand

from uniform import media_cleanup


class Command(BaseCommand):
    help = "Удаляет устаревшие файлы из media (результаты обработки скинов)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age",
            type=float,
            default=None,
            help="Возраст файла в секундах, после которого его удаляют "
                 "(0 — удалить всё; по умолчанию — MEDIA_CLEANUP_MAX_AGE).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Удалить все файлы из media, не глядя на возраст.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Не печатать отчёт (удобно для cron).",
        )

    def handle(self, *args, **options):
        max_age = 0 if options["all"] else options["max_age"]
        report = media_cleanup.cleanup(max_age=max_age)

        if options["quiet"]:
            return

        message = (
            f"Уборка media ({media_cleanup.media_root()}): "
            f"удалено файлов — {report['deleted']}, "
            f"пустых каталогов — {report['dirs']}, "
            f"освобождено — {report['bytes']} байт."
        )
        if report["errors"]:
            message += f" Не удалось удалить файлов: {report['errors']}."
            self.stderr.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))
