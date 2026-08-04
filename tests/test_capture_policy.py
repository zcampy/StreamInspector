from types import SimpleNamespace

import pytest

from streaminspector.capture_policy import (
    CaptureMode,
    CapturePolicy,
    load_capture_policy,
    normalize_domains,
    save_capture_policy,
)


def _flow(host: str, path: str = "/api", content_type: str = "application/json"):
    return SimpleNamespace(host=host, path=path, content_type=content_type)


def test_normalize_domains_removes_wildcards_duplicates_and_spaces() -> None:
    assert normalize_domains(" *.Example.com\nexample.com, api.local ") == (
        "example.com",
        "api.local",
    )


def test_policy_excludes_domain_and_subdomains() -> None:
    policy = CapturePolicy(excluded_domains=("example.com",))
    assert not policy.accepts(_flow("example.com"))
    assert not policy.accepts(_flow("api.example.com"))
    assert policy.accepts(_flow("example.org"))


def test_policy_pauses_all_traffic() -> None:
    policy = CapturePolicy(paused=True)
    assert not policy.accepts(_flow("example.org"))


def test_policy_omits_static_resources_by_type_or_extension() -> None:
    policy = CapturePolicy(omit_static=True)
    assert not policy.accepts(_flow("site.local", content_type="image/png"))
    assert not policy.accepts(_flow("site.local", path="/assets/app.js"))
    assert policy.accepts(_flow("site.local", path="/api/users"))


# -------------------------- CaptureMode.WHITELIST --------------------------


def test_whitelist_mode_accepts_only_whitelisted_domains() -> None:
    """En modo whitelist, SOLO pasan los hosts que estén en la lista
    (incluyendo subdominios). El resto se rechaza."""
    policy = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        whitelisted_domains=("fctv33hd.fit", "adair.sworfa.kdns.fr"),
    )
    # El sitio de stream que el usuario está probando
    assert policy.accepts(_flow("fctv33hd.fit"))
    # El CDN donde está el manifest m3u8
    assert policy.accepts(_flow("adair.sworfa.kdns.fr"))
    # Subdominio del CDN
    assert policy.accepts(_flow("seg.adair.sworfa.kdns.fr"))
    # GitHub Desktop, ChatGPT, telemetría → RECHAZADO
    assert not policy.accepts(_flow("api.github.com"))
    assert not policy.accepts(_flow("chatgpt.com"))
    assert not policy.accepts(_flow("telemetry.microsoft.com"))
    # Hosts "normales" como Google también rechazados
    assert not policy.accepts(_flow("www.google.com"))


def test_whitelist_mode_with_empty_list_rejects_everything() -> None:
    """Si la whitelist está vacía en modo whitelist, NADA pasa — modo
    seguro pero el usuario tiene que añadir dominios para que la app
    capture algo."""
    policy = CapturePolicy(
        mode=CaptureMode.WHITELIST, whitelisted_domains=()
    )
    assert not policy.accepts(_flow("fctv33hd.fit"))
    assert not policy.accepts(_flow("anything.example"))


def test_all_mode_accepts_everything_except_excluded() -> None:
    """En modo ALL, solo se rechazan los `excluded_domains` (más
    paused/omit_static, que ya tienen sus tests)."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        excluded_domains=("ads.example",),
    )
    # Hosts arbitrarios pasan
    assert policy.accepts(_flow("fctv33hd.fit"))
    assert policy.accepts(_flow("github.com"))
    # Pero los excluidos se rechazan
    assert not policy.accepts(_flow("ads.example"))
    assert not policy.accepts(_flow("track.ads.example"))


def test_whitelist_mode_still_respects_paused_and_omit_static() -> None:
    """El modo whitelist NO anula los otros filtros. Si está pausado,
    no captura NADA. Si omit_static=True, sigue omitiendo imágenes."""
    policy = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        paused=True,
        whitelisted_domains=("fctv33hd.fit",),
    )
    assert not policy.accepts(_flow("fctv33hd.fit"))

    policy2 = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        whitelisted_domains=("fctv33hd.fit",),
        omit_static=True,
    )
    # Aunque esté en la whitelist, una imagen se omite
    assert not policy2.accepts(
        _flow("fctv33hd.fit", path="/logo.png", content_type="image/png")
    )
    # Un manifest m3u8 sí
    assert policy2.accepts(
        _flow(
            "fctv33hd.fit",
            path="/index.m3u8",
            content_type="application/vnd.apple.mpegurl",
        )
    )


# -------------------------- load/save_capture_policy -----------------------


class _FakeSettings:
    """QSettings mínimo para tests: dict con setValue/getValue.

    Simula la API que `load_capture_policy` y `save_capture_policy`
    necesitan: `.value(key, default)` y `.setValue(key, value)`.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = dict(data or {})

    def value(self, key: str, default=None):  # noqa: ANN001 - duck typing
        return self._data.get(key, default)

    def setValue(self, key: str, value) -> None:  # noqa: ANN001 - duck typing
        self._data[key] = value

    def data(self) -> dict:
        return dict(self._data)


def test_load_capture_policy_defaults_to_whitelist_safe_mode() -> None:
    """Sin QSettings previo, el loader devuelve WHITELIST (modo seguro
    por defecto: el usuario solo captura lo que ha añadido explícitamente)."""
    settings = _FakeSettings()
    policy = load_capture_policy(settings)
    assert policy.mode is CaptureMode.WHITELIST
    assert policy.excluded_domains == ()
    assert policy.whitelisted_domains == ()
    assert policy.omit_static is False


def test_load_capture_policy_tolerates_corrupt_mode_value() -> None:
    """Si el valor de `capture/mode` en QSettings no es un CaptureMode
    válido, el loader cae a WHITELIST (modo seguro) en lugar de lanzar
    excepción al arrancar. Mejor restringir captura que romper el inicio."""
    settings = _FakeSettings({"capture/mode": "esto-no-es-un-modo-valido"})
    policy = load_capture_policy(settings)
    assert policy.mode is CaptureMode.WHITELIST


def test_save_and_load_capture_policy_roundtrip() -> None:
    """Lo que guardas con save_capture_policy se recupera con load."""
    settings = _FakeSettings()
    original = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        excluded_domains=("ads.example", "tracker.com"),
        whitelisted_domains=("fctv33hd.fit", "adair.sworfa.kdns.fr"),
        omit_static=True,
    )
    save_capture_policy(settings, original)
    loaded = load_capture_policy(settings)
    assert loaded.mode is CaptureMode.WHITELIST
    assert loaded.excluded_domains == ("ads.example", "tracker.com")
    assert loaded.whitelisted_domains == (
        "fctv33hd.fit",
        "adair.sworfa.kdns.fr",
    )
    assert loaded.omit_static is True


def test_save_capture_policy_normalizes_list_format() -> None:
    """save_capture_policy guarda los dominios como string con '\\n'.
    Es el formato que entiende `QInputDialog.getMultiLineText`."""
    settings = _FakeSettings()
    policy = CapturePolicy(
        whitelisted_domains=("a.example", "b.example"),
        excluded_domains=("c.example",),
    )
    save_capture_policy(settings, policy)
    data = settings.data()
    assert data["capture/whitelisted_domains"] == "a.example\nb.example"
    assert data["capture/excluded_domains"] == "c.example"
    assert data["capture/mode"] == "all"  # default mode
    assert data["capture/omit_static"] is False


@pytest.mark.parametrize("mode", [CaptureMode.ALL, CaptureMode.WHITELIST])
def test_capture_mode_roundtrips_through_settings(mode) -> None:
    settings = _FakeSettings()
    save_capture_policy(settings, CapturePolicy(mode=mode))
    loaded = load_capture_policy(settings)
    assert loaded.mode is mode
