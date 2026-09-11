"""
Актуальный скин игрока по нику.

Почему не NameMC напрямую
-------------------------
Страницы профилей на namemc.com закрыты Cloudflare-челленджем: запрос с сервера
(без настоящего браузера) получает HTTP 403 и страницу «Just a moment...»,
публичного API профилей у NameMC нет (``api.namemc.com`` умеет только серверы).
При этом NameMC ничего не хранит сам: и текстуру скина, и модель игрока
(classic/slim) он показывает из официальных API Mojang. Поэтому берём скин там
же, где его берёт NameMC, — данные те же и всегда актуальные.

Что используем
--------------
1. ``api.minecraftservices.com/minecraft/profile/lookup/name/<ник>`` — UUID по нику
   (запасной адрес — ``api.mojang.com/users/profiles/minecraft/<ник>``).
2. ``sessionserver.mojang.com/session/minecraft/profile/<uuid>`` — свойство
   ``textures`` (base64 JSON): ссылка на PNG скина и, для slim-скинов,
   ``metadata.model = "slim"``. Этот признак и определяет формат скина.
3. ``textures.minecraft.net/texture/<hash>`` — сам PNG.

Ответы кэшируются в памяти процесса на ``CACHE_TTL`` секунд, чтобы один и тот же
ник не дёргал Mojang на каждое действие (предпросмотр + отправка формы).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import skin_formats

#: Официальные адреса Mojang: сначала актуальный, затем прежний (запасной).
NAME_LOOKUP_URLS = (
    "https://api.minecraftservices.com/minecraft/profile/lookup/name/{nickname}",
    "https://api.mojang.com/users/profiles/minecraft/{nickname}",
)

#: Профиль игрока с подписанным свойством textures.
PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"

#: Хранилище текстур Minecraft — откуда скачивается PNG скина.
TEXTURE_HOST = "https://textures.minecraft.net/texture/"

#: Ник в Minecraft: латиница, цифры и «_». Короткие ники (1–2 символа) —
#: это легаси-аккаунты, они тоже ищутся.
NICKNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

#: Таймаут одного запроса к Mojang, секунды.
TIMEOUT = 10

#: Сколько секунд держать ответ в кэше.
CACHE_TTL = 300

USER_AGENT = "uniform-applicator/1.0"


class ProfileError(Exception):
    """Ошибка получения скина; текст можно показывать пользователю."""


@dataclass(frozen=True)
class Profile:
    """Скин игрока, полученный от Mojang."""

    nickname: str
    uuid: str
    skin_format: str
    skin_png: bytes


class _HttpError(Exception):
    """Внутренняя ошибка запроса: вид проблемы + техническая подробность."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


_cache: dict[str, tuple[float, Profile]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    """Очищает кэш профилей (нужно тестам и после ручных правок)."""
    with _cache_lock:
        _cache.clear()


def fetch_skin(nickname: str) -> Profile:
    """
    Возвращает актуальный скин игрока по нику.

    Бросает ``ProfileError`` с готовым для показа текстом: ник не найден,
    Mojang ограничил запросы, нет связи, у игрока нет скина и т.п.
    """
    nickname = (nickname or "").strip()

    if not NICKNAME_RE.match(nickname):
        raise ProfileError(
            "Ник может состоять из латинских букв, цифр и «_» — до 16 символов."
        )

    cached = _cache_get(nickname)
    if cached is not None:
        return cached

    try:
        player_id, name = _lookup_player(nickname)
        skin_url, skin_format = _lookup_skin(player_id)
        skin_png = _download_skin(skin_url)
    except _HttpError as exc:
        raise ProfileError(_user_message(exc, nickname)) from None

    profile = Profile(
        nickname=name, uuid=player_id, skin_format=skin_format, skin_png=skin_png
    )
    _cache_put(nickname, profile)
    return profile


# ---------------------------------------------------------------------------
# Запросы к Mojang
# ---------------------------------------------------------------------------

def _request(url: str) -> bytes:
    """GET к Mojang; сетевые ошибки и коды ответа приводит к ``_HttpError``."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise _HttpError("not_found") from exc
        if exc.code == 429:
            raise _HttpError("rate_limited") from exc
        raise _HttpError("server", f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _HttpError("network", str(exc)) from exc


def _lookup_player(nickname: str) -> tuple[str, str]:
    """
    UUID и точное написание ника по нику игрока.

    Адреса перебираются по порядку: если один недоступен, пробуем следующий.
    Если не вышло ни с одним — сообщаем самую полезную из полученных ошибок
    (ограничение частоты важнее сетевой, сетевая — важнее прочей),
    а не абстрактное «сервер ответил ошибкой».
    """
    quoted = urllib.parse.quote(nickname, safe="")
    errors: list[_HttpError] = []

    for template in NAME_LOOKUP_URLS:
        try:
            payload = json.loads(_request(template.format(nickname=quoted)).decode("utf-8"))
        except _HttpError as exc:
            if exc.kind == "not_found":
                raise
            errors.append(exc)
            continue
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append(_HttpError("server", "некорректный ответ"))
            continue

        player_id = payload.get("id")
        if player_id:
            return player_id, payload.get("name") or nickname

        errors.append(_HttpError("server", "в ответе нет UUID"))

    raise _most_important(errors)


#: Что важнее сообщить пользователю, если все адреса отказали.
_ERROR_PRIORITY = ("rate_limited", "network", "server")


def _most_important(errors: list[_HttpError]) -> _HttpError:
    for kind in _ERROR_PRIORITY:
        for error in errors:
            if error.kind == kind:
                return error
    return errors[-1] if errors else _HttpError("server")


def _lookup_skin(player_id: str) -> tuple[str, str]:
    """Ссылка на PNG скина и формат скина (classic/slim)."""
    try:
        payload = json.loads(_request(PROFILE_URL.format(uuid=player_id)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProfileError("Не удалось разобрать ответ Mojang о скине игрока.") from None

    skin = _textures(payload).get("SKIN") or {}
    url = skin.get("url")
    if not url:
        raise ProfileError("У этого игрока нет скина на серверах Mojang.")

    # В ответе ссылка на http, хотя хост умеет https.
    if url.startswith("http://textures.minecraft.net/"):
        url = "https://" + url[len("http://"):]

    model = (skin.get("metadata") or {}).get("model")
    skin_format = skin_formats.SLIM if model == "slim" else skin_formats.CLASSIC
    return url, skin_format


def _download_skin(url: str) -> bytes:
    """Скачивает PNG скина (только с хранилища текстур Minecraft)."""
    if not url.startswith(TEXTURE_HOST):
        raise ProfileError("Mojang вернул неожиданную ссылку на скин.")
    return _request(url)


def _textures(payload: dict) -> dict:
    """Достаёт словарь textures из base64-свойства профиля."""
    for prop in payload.get("properties") or []:
        if prop.get("name") != "textures":
            continue
        try:
            raw = base64.b64decode(prop.get("value") or "", validate=True)
            return json.loads(raw.decode("utf-8")).get("textures") or {}
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            break
    raise ProfileError("Не удалось разобрать ответ Mojang о скине игрока.")


def _user_message(error: _HttpError, nickname: str) -> str:
    """Текст ошибки, который не стыдно показать пользователю."""
    if error.kind == "not_found":
        return f"Игрок с ником «{nickname}» не найден."
    if error.kind == "rate_limited":
        return "Mojang ограничил частоту запросов — попробуйте через минуту."
    if error.kind == "network":
        return "Не удалось связаться с серверами Mojang. Проверьте соединение и попробуйте снова."
    return "Серверы Mojang ответили ошибкой. Попробуйте позже."


# ---------------------------------------------------------------------------
# Кэш
# ---------------------------------------------------------------------------

def _cache_get(nickname: str) -> Profile | None:
    with _cache_lock:
        item = _cache.get(nickname.lower())
    if item is None:
        return None
    stored_at, profile = item
    if time.monotonic() - stored_at > CACHE_TTL:
        return None
    return profile


def _cache_put(nickname: str, profile: Profile) -> None:
    with _cache_lock:
        _cache[nickname.lower()] = (time.monotonic(), profile)
