"""
Автоочистка каталога media.

Результаты обработки (``media/processed/<uuid>_<формат>.png``) — временные: их
скачивают или открывают в Blockbench сразу после обработки, дальше они только
занимают место. Чтобы каталог не рос бесконечно, приложение само удаляет из
media устаревшие файлы.

Уборка запускается двумя путями:

* **сама** — фоновый поток, который просыпается каждые ``MEDIA_CLEANUP_INTERVAL``
  секунд (по умолчанию 30 минут) и удаляет файлы старше ``MEDIA_CLEANUP_MAX_AGE``
  секунд (по умолчанию тоже 30 минут, то есть файл живёт от 30 до 60 минут).
  Поток поднимается из ``config/wsgi.py`` и ``config/asgi.py`` — то есть только
  в процессе веб-сервера, команды ``manage.py`` его не запускают.
  Отключается переменной окружения ``DJANGO_MEDIA_CLEANUP=0``.
* **по команде** — ``python manage.py clean_media``: для cron или Планировщика
  задач Windows, если фоновый поток в вашем окружении не подходит
  (несколько воркеров, отдельный сервис уборки и т.п.).

``MEDIA_CLEANUP_MAX_AGE = 0`` означает «удалять всё» — тогда каждый запуск
уборки полностью очищает каталог.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Значения по умолчанию, если настройки не заданы (30 минут).
DEFAULT_INTERVAL = 30 * 60
DEFAULT_MAX_AGE = 30 * 60

#: Фоновый поток уборки, события его остановки и время последней уборки.
_thread: threading.Thread | None = None
_stop = threading.Event()
_last_run = 0.0
_lock = threading.Lock()


def media_root() -> Path:
    """Каталог media из настроек."""
    return Path(settings.MEDIA_ROOT)


def cleanup(max_age: float | None = None) -> dict:
    """
    Удаляет устаревшие файлы из media.

    ``max_age`` — возраст в секундах, после которого файл считается мусором;
    ``0`` — удалять все файлы; ``None`` — взять ``MEDIA_CLEANUP_MAX_AGE``
    из настроек. Служебные файлы (начинающиеся с точки, например ``.gitkeep``)
    не трогаем, пустые подкаталоги убираем, сам media — оставляем.

    Возвращает отчёт: ``deleted`` — сколько файлов удалено, ``bytes`` —
    сколько освобождено, ``dirs`` — сколько пустых каталогов убрано,
    ``errors`` — сколько файлов не удалось удалить.
    """
    if max_age is None:
        max_age = getattr(settings, "MEDIA_CLEANUP_MAX_AGE", DEFAULT_MAX_AGE)

    root = media_root()
    report = {"deleted": 0, "bytes": 0, "dirs": 0, "errors": 0}

    if not root.is_dir():
        return report

    deadline = time.time() - max_age

    for dirpath, _dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(dirpath)

        for name in filenames:
            if name.startswith("."):
                continue

            path = current / name
            try:
                stat = path.stat()
                if max_age and stat.st_mtime > deadline:
                    continue
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                report["errors"] += 1
                logger.warning("Не удалось удалить %s: %s", path, exc)
                continue

            report["deleted"] += 1
            report["bytes"] += stat.st_size

        # Пустые подкаталоги убираем, сам media оставляем на месте.
        if current != root:
            try:
                current.rmdir()
                report["dirs"] += 1
            except OSError:
                pass

    return report


def run_if_due(now: float | None = None) -> dict | None:
    """
    Запускает уборку, если с прошлой не прошло ``MEDIA_CLEANUP_INTERVAL`` секунд.

    Возвращает отчёт об уборке или ``None``, если уборка ещё не полагается.
    """
    global _last_run

    interval = getattr(settings, "MEDIA_CLEANUP_INTERVAL", DEFAULT_INTERVAL)
    moment = time.monotonic() if now is None else now

    with _lock:
        if _last_run and moment - _last_run < interval:
            return None
        _last_run = moment

    return cleanup()


def start_scheduler() -> threading.Thread | None:
    """
    Поднимает фоновый поток уборки — по одному на процесс.

    Вызывается из точки входа веб-сервера (``config/wsgi.py``, ``config/asgi.py``),
    поэтому команды ``manage.py`` (migrate, test, collectstatic) уборку не
    запускают. Повторные вызовы возвращают уже запущенный поток.
    """
    global _thread

    if not getattr(settings, "MEDIA_CLEANUP_ENABLED", True):
        return None

    with _lock:
        if _thread is not None and _thread.is_alive():
            return _thread

        interval = getattr(settings, "MEDIA_CLEANUP_INTERVAL", DEFAULT_INTERVAL)
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, args=(interval,), name="media-cleanup", daemon=True
        )
        _thread.start()
        logger.info(
            "Автоочистка media запущена: каждые %s с, файлы старше %s с",
            interval,
            getattr(settings, "MEDIA_CLEANUP_MAX_AGE", DEFAULT_MAX_AGE),
        )
        return _thread


def stop_scheduler(timeout: float = 2.0) -> None:
    """Останавливает фоновый поток уборки (нужно тестам и аккуратному выходу)."""
    global _thread

    with _lock:
        thread = _thread
        _thread = None
    if thread is None:
        return

    _stop.set()
    thread.join(timeout=timeout)


def _loop(interval: float) -> None:
    """Тело фонового потока: уборка сразу и далее каждые ``interval`` секунд."""
    while True:
        try:
            report = run_if_due()
            if report and report["deleted"]:
                logger.info(
                    "Автоочистка media: удалено файлов — %s, пустых каталогов — %s, "
                    "освобождено — %s байт",
                    report["deleted"], report["dirs"], report["bytes"],
                )
        except Exception:  # уборка не должна ронять поток
            logger.exception("Ошибка автоочистки media")
        if _stop.wait(interval):
            return
