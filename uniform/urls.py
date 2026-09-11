"""URL-адреса приложения uniform (одностраничник)."""

from django.urls import path

from . import views

app_name = "uniform"

urlpatterns = [
    # Главная и единственная страница: GET — форма, POST — обработка.
    path("", views.index, name="index"),
    # Скин игрока по нику (для предпросмотра) — данные Mojang.
    path("skin/<str:nickname>/", views.skin_by_nickname, name="skin_by_nickname"),
    # Переход в веб-редактор Blockbench с готовым скином.
    path("blockbench/<str:filename>/", views.blockbench_editor, name="blockbench"),
]
