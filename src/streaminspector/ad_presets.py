"""Listas curadas de dominios de publicidad y tracking.

Estos presets se pueden cargar con un click desde el menú `Captura > Cargar
lista de exclusión de ads` para reducir el ruido en las capturas cuando el
usuario navega sitios web con muchas redes de ads.

Cada dominio se trata con la misma lógica que `CapturePolicy.excluded_domains`:
cubre el dominio y todos sus subdominios.

La lista es deliberadamente conservadora — solo incluye dominios que son
*claramente* de ads/tracking, no servicios legítimos. Si bloqueas algo que
necesitas, siempre puedes editarlo desde `Captura > Configurar dominios
excluidos…`.
"""

from __future__ import annotations

# Formato: tupla de strings. Los puntos finales y "www." se normalizan en
# `normalize_domains`, así que da igual si vienen con o sin prefijo.
COMMON_AD_DOMAINS: tuple[str, ...] = (
    # Google ad ecosystem
    "doubleclick.net",
    "googlesyndication.com",
    "googletagservices.com",
    "adservice.google.com",
    "admob.com",
    # Facebook / Meta tracking
    "connect.facebook.net",
    # Amazon ads
    "amazon-adsystem.com",
    # Major ad networks
    "criteo.com",
    "criteo.net",
    "taboola.com",
    "outbrain.com",
    "adnxs.com",
    "adsrvr.org",
    "adroll.com",
    "mathtag.com",
    "rubiconproject.com",
    "magnite.com",
    # Analytics & tracking
    "scorecardresearch.com",
    "quantserve.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "branch.io",
    "adjust.com",
    # Ad verification
    "doubleverify.com",
    "moatads.com",
)


def merge_ad_preset(existing: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Devuelve `existing` + el preset de ads, sin duplicados, en el orden
    en que aparecen.

    `existing` puede ser la tupla actual de `CapturePolicy.excluded_domains`.
    El preset se añade al final para que el usuario pueda ver en el diálogo
    "Configurar dominios excluidos" qué entradas vienen de dónde (las suyas
    primero, la lista curada después).
    """
    return _merge_preset(existing, COMMON_AD_DOMAINS)


# Dominios de CDNs de stream vistos en capturas reales de StreamInspector.
# El usuario abre un sitio web de streaming (ej: fctv33hd.fit) y el sitio
# carga manifests m3u8/segmentos desde hosts que cambian o están obfuscados
# (sworfa.kdns.fr, fhlsport720.tm33bpoughss0281full.ru, etc.). Con esta
# lista precargada en el modo WHITELIST, StreamInspector deja pasar
# transparente el resto del sistema y solo captura estos CDNs.
COMMON_STREAM_CDN_DOMAINS: tuple[str, ...] = (
    # Sitios de stream que el usuario prueba en el navegador
    "fctv33hd.fit",
    # CDNs observados en los CSVs de captura que sirven los manifests/segmentos
    "adair.sworfa.kdns.fr",
    "sworfa.kdns.fr",
    "fhlsport720.tm33bpoughss0281full.ru",
    "tm33bpoughss0281full.ru",
)


def merge_stream_preset(existing: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Igual que `merge_ad_preset` pero para el preset de CDNs de stream.

    Pensado para el campo `CapturePolicy.whitelisted_domains` cuando se
    activa el modo `WHITELIST`. Si el usuario ya tenía dominios propios
    en la whitelist, se preservan; los del preset se añaden al final.
    """
    return _merge_preset(existing, COMMON_STREAM_CDN_DOMAINS)


def _merge_preset(
    existing: tuple[str, ...] | list[str], preset: tuple[str, ...]
) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for source in (existing, preset):
        for domain in source:
            normalized = domain.strip().lower().lstrip("*.").rstrip(".")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return tuple(merged)
