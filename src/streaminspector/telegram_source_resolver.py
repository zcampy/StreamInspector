"""Resuelve la URL pública vigente publicada en un canal público de Telegram."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

TELEGRAM_CHANNEL = "juegoloco77_k"
TELEGRAM_PREVIEW_URL = f"https://t.me/s/{TELEGRAM_CHANNEL}"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
_MESSAGE_RE = re.compile(
    r'<div[^>]+class="[^"]*tgme_widget_message_wrap[^"]*"[^>]*>(.*?)'
    r'(?=<div[^>]+class="[^"]*tgme_widget_message_wrap|\Z)',
    re.I | re.S,
)
_HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)
_TEXT_URL_RE = re.compile(r'https?://[^\s<>&"\']+', re.I)

_IGNORED_HOSTS = {
    "t.me",
    "telegram.me",
    "www.telegram.me",
    "telegram.org",
    "www.telegram.org",
    "twitter.com",
    "x.com",
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "wa.me",
    "whatsapp.com",
    "www.whatsapp.com",
}


@dataclass(frozen=True, slots=True)
class SourceResolution:
    url: str | None
    message: str
    telegram_url: str = TELEGRAM_PREVIEW_URL


def _request(url: str, timeout: float = 8.0) -> tuple[bytes, str]:
    opener = build_opener(ProxyHandler({}))
    request = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        },
        method="GET",
    )
    with opener.open(request, timeout=timeout) as response:  # noqa: S310 - HTTPS público
        return response.read(2_000_000), response.geturl()


def _normalise_candidate(raw_url: str) -> str | None:
    raw_url = unescape(raw_url).strip().rstrip(".,);]}")
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if host in _IGNORED_HOSTS or host.endswith(".t.me"):
        return None
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def extract_external_urls(html: str) -> list[str]:
    """Devuelve URLs externas desde mensajes, de más recientes a más antiguas."""
    messages = _MESSAGE_RE.findall(html)
    if not messages:
        messages = [html]

    found: list[str] = []
    seen: set[str] = set()
    for message in reversed(messages):
        raw_urls = [*_HREF_RE.findall(message), *_TEXT_URL_RE.findall(unescape(message))]
        for raw in raw_urls:
            candidate = _normalise_candidate(raw)
            if candidate is None or candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
    return found


def validate_public_site(url: str, timeout: float = 6.0) -> str | None:
    """Valida que una URL pública responda y devuelve su URL final tras redirecciones."""
    try:
        _body, final_url = _request(url, timeout=timeout)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    return _normalise_candidate(final_url)


def resolve_latest_public_site(
    channel_url: str = TELEGRAM_PREVIEW_URL,
    *,
    timeout: float = 8.0,
    validate: bool = True,
) -> SourceResolution:
    try:
        body, _final = _request(channel_url, timeout=timeout)
    except HTTPError as exc:
        return SourceResolution(None, f"Telegram respondió HTTP {exc.code}", channel_url)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return SourceResolution(None, f"No se pudo consultar Telegram: {exc}", channel_url)

    html = body.decode("utf-8", errors="replace")
    candidates = extract_external_urls(html)
    if not candidates:
        return SourceResolution(None, "No se encontró ninguna URL externa en los mensajes recientes", channel_url)

    if not validate:
        return SourceResolution(candidates[0], "URL pública más reciente encontrada en Telegram", channel_url)

    for candidate in candidates[:12]:
        validated = validate_public_site(candidate, timeout=min(timeout, 6.0))
        if validated:
            return SourceResolution(validated, "URL pública vigente resuelta desde Telegram", channel_url)

    return SourceResolution(None, "Se encontraron URLs, pero ninguna respondió correctamente", channel_url)


def football_page_from_site(site_url: str) -> str:
    """Construye la página de fútbol a partir de la URL pública vigente del sitio."""
    parts = urlsplit(site_url)
    path = parts.path.rstrip("/")
    if path.endswith("/football.html"):
        football_path = path
    elif path.endswith("/es"):
        football_path = path + "/football.html"
    else:
        football_path = "/es/football.html"
    return urlunsplit((parts.scheme, parts.netloc, football_path, "", ""))
