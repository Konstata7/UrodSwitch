"""
Конфигурация URL проекта «Uniform Applicator».

Единственная страница сайта — '/', на ней же обрабатывается
загрузка файлов (POST). /admin/ доступен для служебных нужд.
"""

from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.urls import include, path, re_path
from django.views.static import serve


def _media_serve(request, path):
    """Раздача медиафайлов: только при DEBUG, MEDIA_ROOT — в момент запроса."""
    if not settings.DEBUG:
        raise Http404("Медиафайлы отдаются только в режиме отладки.")
    return serve(request, path, document_root=settings.MEDIA_ROOT)


# Заголовки админки (удобно, если админка будет использоваться).
admin.site.site_header = "Uniform Applicator"
admin.site.site_title = "Uniform Applicator"
admin.site.index_title = "Управление"

urlpatterns = [
    path("", include("uniform.urls")),
    path("admin/", admin.site.urls),
    # Раздача загруженных/сгенерированных файлов (только при DEBUG — см. выше).
    # В проде медиафайлы отдаёт веб-сервер (nginx и т.п.).
    re_path(r"^media/(?P<path>.*)$", _media_serve),
]
