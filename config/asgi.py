"""
ASGI config for UrodSwitch project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()

# Автоочистка media: тот же фоновый поток, что и в WSGI-точке входа
# (см. config/wsgi.py и uniform/media_cleanup.py).
from uniform import media_cleanup  # noqa: E402

media_cleanup.start_scheduler()
