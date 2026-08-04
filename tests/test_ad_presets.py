"""Tests para la lista curada de ads/trackers y su fusión con dominios
existentes."""

from __future__ import annotations

from streaminspector.ad_presets import COMMON_AD_DOMAINS, merge_ad_preset


def test_common_ad_domains_contains_well_known_networks() -> None:
    """La lista debe incluir los nombres grandes que aparecen en cualquier
    captura de un sitio web moderno. Si falla, alguien quitó un preset clave.
    """
    expected = {
        "doubleclick.net",
        "googlesyndication.com",
        "criteo.com",
        "taboola.com",
        "outbrain.com",
        "amazon-adsystem.com",
        "connect.facebook.net",
    }
    assert expected.issubset(set(COMMON_AD_DOMAINS)), (
        f"Faltan dominios clave: {expected - set(COMMON_AD_DOMAINS)}"
    )


def test_common_ad_domains_has_no_duplicates() -> None:
    assert len(COMMON_AD_DOMAINS) == len(set(COMMON_AD_DOMAINS))


def test_common_ad_domains_are_lowercase() -> None:
    for domain in COMMON_AD_DOMAINS:
        assert domain == domain.lower(), f"{domain!r} no está en minúsculas"


def test_common_ad_domains_have_no_protocol_or_path() -> None:
    for domain in COMMON_AD_DOMAINS:
        assert "://" not in domain, f"{domain!r} tiene protocolo"
        assert "/" not in domain, f"{domain!r} tiene path"
        assert " " not in domain, f"{domain!r} tiene espacios"


def test_merge_adds_preset_to_empty_list() -> None:
    merged = merge_ad_preset(())
    assert set(merged) == set(COMMON_AD_DOMAINS)
    assert len(merged) == len(COMMON_AD_DOMAINS)


def test_merge_preserves_existing_and_adds_new() -> None:
    existing = ("example.com", "tracker.io")
    merged = merge_ad_preset(existing)

    # Los del usuario van primero
    assert merged[:2] == ("example.com", "tracker.io")
    # Los del preset se añaden al final sin duplicar los del usuario
    for domain in existing:
        assert domain in merged
    assert len(merged) == len(existing) + len(COMMON_AD_DOMAINS)


def test_merge_dedupes_overlap_with_preset() -> None:
    """Si el usuario ya tenía un dominio del preset, no se duplica."""
    existing = ("doubleclick.net", "example.com")
    merged = merge_ad_preset(existing)
    assert "doubleclick.net" in merged
    assert merged.count("doubleclick.net") == 1
    # example.com se preserva (del usuario), doubleclick.net también (1 sola vez)
    assert len(merged) == 1 + len(COMMON_AD_DOMAINS)


def test_merge_handles_string_with_whitespace_and_dots() -> None:
    existing = ("  example.com  ", "WWW.tracker.io", "*.nested.org.")
    merged = merge_ad_preset(existing)
    # Los dos primeros se normalizan a minúsculas sin espacios/wildcard
    assert "example.com" in merged
    assert "www.tracker.io" in merged
    assert "nested.org" in merged


def test_merge_accepts_list_input() -> None:
    """La API acepta tanto `tuple` como `list` (cualquier iterable realmente)."""
    merged = merge_ad_preset(["example.com"])
    assert "example.com" in merged


def test_merge_idempotent() -> None:
    """Aplicar el preset dos veces produce el mismo resultado que una vez."""
    once = merge_ad_preset(())
    twice = merge_ad_preset(once)
    assert once == twice
