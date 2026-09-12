"""
Настройки Django-проекта «UrodSwitch».

Одностраничный сайт: загрузка скина и формы (uniform), наложение
формы на скин, предпросмотр и скачивание результата.

Значения берутся из переменных окружения с безопасными значениями
по умолчанию для локальной разработки:
    DJANGO_SECRET_KEY      — секретный ключ (в проде задавать обязательно)
    DJANGO_DEBUG           — '1'/'true' — режим отладки (по умолчанию вкл.)
    DJANGO_ALLOWED_HOSTS   — список хостов через запятую
    DJANGO_MEDIA_CLEANUP   — '0'/'false' — выключить автоочистку media
    DJANGO_MEDIA_CLEANUP_INTERVAL — как часто убирать media, секунды (1800)
    DJANGO_MEDIA_CLEANUP_MAX_AGE  — возраст файлов для удаления, секунды (1800)
"""

import os
from pathlib import Path

# Корень проекта (каталог, где лежат manage.py, config/, uniform/).
BASE_DIR = Path(__file__).resolve().parent.parent


def _env_flag(name: str, default: bool = False) -> bool:
    """Читает булеву переменную окружения ('1', 'true', 'yes', 'on')."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Читает целочисленную переменную окружения (секунды)."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


# SECURITY WARNING: держите ключ в секрете; в проде задайте DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-kn6y8xk1wq!(dev-only-key)urodswitch-7z#m@+q2v9$r4h",
)

# SECURITY WARNING: не запускайте с включённым DEBUG в проде!
DEBUG = _env_flag("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Приложение одностраничника.
    "uniform.apps.UniformConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Сюда можно класть общие шаблоны (base.html и т.п.); шаблоны
        # приложения Django ищет сам в uniform/templates/.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Password validation
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/

LANGUAGE_CODE = "ru-ru"

TIME_ZONE = "Europe/Moscow"

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/stable/howto/static-files/

STATIC_URL = "static/"
# Каталог, куда `manage.py collectstatic` складывает файлы для прода.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (результаты обработки)
# https://docs.djangoproject.com/en/stable/topics/files/

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Автоочистка media
# Результаты обработки — временные файлы, поэтому приложение само убирает
# из media всё, что старше MEDIA_CLEANUP_MAX_AGE секунд, проверяя каталог
# каждые MEDIA_CLEANUP_INTERVAL секунд (по умолчанию 30 минут и 30 минут:
# файл живёт от получаса до часа). MEDIA_CLEANUP_MAX_AGE = 0 — удалять всё.
# Поток уборки поднимается из config/wsgi.py и config/asgi.py, то есть
# работает только в процессе веб-сервера; для cron есть команда
# `python manage.py clean_media`.
MEDIA_CLEANUP_ENABLED = _env_flag("DJANGO_MEDIA_CLEANUP", default=True)
MEDIA_CLEANUP_INTERVAL = _env_int("DJANGO_MEDIA_CLEANUP_INTERVAL", 30 * 60)
MEDIA_CLEANUP_MAX_AGE = _env_int("DJANGO_MEDIA_CLEANUP_MAX_AGE", 30 * 60)

# Default primary key field type
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Logging
# Первым Django применяет свою настройку (DEFAULT_LOGGING), а затем эту — и во
# втором проходе имена хендлеров из стандартной настройки уже недоступны,
# поэтому хендлер описан здесь полностью. Пишем только при DEBUG=True и не
# трогаем логгеры Django (disable_existing_loggers=False).

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "require_debug_true": {"()": "django.utils.log.RequireDebugTrue"},
    },
    "formatters": {
        "app": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "app_console": {
            "class": "logging.StreamHandler",
            "filters": ["require_debug_true"],
            "formatter": "app",
        },
    },
    "loggers": {
        "uniform": {"handlers": ["app_console"], "level": "INFO", "propagate": False},
    },
}
