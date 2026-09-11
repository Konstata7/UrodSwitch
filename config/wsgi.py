"""
WSGI config for uniform_applicator project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# Автоочистка media: фоновый поток живёт в процессе веб-сервера — этот файл
# импортирует и runserver, и продовый WSGI-сервер. Команды manage.py (migrate,
# test, collectstatic) сюда не заходят, поэтому уборку не запускают.
# Выключается переменной окружения DJANGO_MEDIA_CLEANUP=0.
from uniform import media_cleanup  # noqa: E402

media_cleanup.start_scheduler()
