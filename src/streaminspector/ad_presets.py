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
    seen: set[str] = set()
    merged: list[str] = []
    for source in (existing, COMMON_AD_DOMAINS):
        for domain in source:
            normalized = domain.strip().lower().lstrip("*.").rstrip(".")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return tuple(merged)
