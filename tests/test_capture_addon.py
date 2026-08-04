"""Tests del `CaptureAddon`: confirmar que el filtro del policy se aplica
a nivel de proxy (no solo en storage), para que los datos sensibles de
apps que no están en la whitelist ni siquiera lleguen al EventBus."""

from __future__ import annotations

from streaminspector.capture_policy import CaptureMode, CapturePolicy
from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.proxy.addon import CaptureAddon


class _FakeFlow:
    """Replica mínima de `mitmproxy.http.HTTPFlow` con los atributos
    que `CaptureAddon.response` lee. Evita levantar el proxy real."""

    def __init__(
        self,
        *,
        host: str = "example.com",
        method: str = "GET",
        path: str = "/",
        scheme: str = "https",
        port: int = 443,
        status: int = 200,
        content_type: str = "text/html",
        body: bytes = b"<html>ok</html>",
    ) -> None:
        self.id = f"flow-{host}"
        self.request = _FakeRequest(
            host=host,
            method=method,
            path=path,
            scheme=scheme,
            port=port,
        )
        self.response = _FakeResponse(
            status=status, content_type=content_type, body=body
        )


class _FakeRequest:
    def __init__(self, host, method, path, scheme, port) -> None:
        self.host = host
        self.method = method
        self.path = path
        self.scheme = scheme
        self.port = port
        self.http_version = "HTTP/1.1"
        self.pretty_url = f"{scheme}://{host}{path}"
        self.headers = _FakeHeaders({})
        self.raw_content = b""
        self.timestamp_start = 0.0

    def headers_items(self):
        return tuple(self.headers.items(multi=True))


class _FakeResponse:
    def __init__(self, status, content_type, body) -> None:
        self.status_code = status
        self.reason = "OK"
        self.raw_content = body
        self.headers = _FakeHeaders({"content-type": content_type})
        self.timestamp_end = 0.0


class _FakeHeaders:
    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def items(self, multi: bool = False):
        return tuple(self._data.items())


def test_addon_publishes_for_all_mode_by_default() -> None:
    """Sin whitelist (modo ALL), el addon emite para todos los hosts."""
    bus = EventBus()
    published: list[HttpFlowCaptured] = []
    bus.subscribe(HttpFlowCaptured, lambda e: published.append(e))

    policy = CapturePolicy(mode=CaptureMode.ALL)
    addon = CaptureAddon(bus, policy)

    addon.response(_FakeFlow(host="api.github.com"))
    addon.response(_FakeFlow(host="chatgpt.com"))
    addon.response(_FakeFlow(host="fctv33hd.fit"))

    assert len(published) == 3
    hosts = {p.host for p in published}
    assert hosts == {"api.github.com", "chatgpt.com", "fctv33hd.fit"}


def test_addon_filters_out_non_whitelisted_hosts_in_whitelist_mode() -> None:
    """El test crítico de privacidad: en modo WHITELIST, el addon
    SOLO emite `HttpFlowCaptured` para hosts en la whitelist. Las
    peticiones de GitHub/ChatGPT/telemetría NO se publican al bus,
    por lo que nunca llegan al storage ni quedan en memoria."""
    bus = EventBus()
    published: list[HttpFlowCaptured] = []
    bus.subscribe(HttpFlowCaptured, lambda e: published.append(e))

    policy = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        whitelisted_domains=("fctv33hd.fit", "adair.sworfa.kdns.fr"),
    )
    addon = CaptureAddon(bus, policy)

    # Tráfico del sitio de stream → pasa
    addon.response(_FakeFlow(host="fctv33hd.fit"))
    addon.response(_FakeFlow(host="adair.sworfa.kdns.fr"))
    # Subdominio del CDN → pasa
    addon.response(_FakeFlow(host="seg.adair.sworfa.kdns.fr"))
    # Tráfico de otras apps → BLOQUEADO en el addon, no llega al bus
    addon.response(_FakeFlow(host="api.github.com"))
    addon.response(_FakeFlow(host="chatgpt.com"))
    addon.response(_FakeFlow(host="telemetry.microsoft.com"))
    addon.response(_FakeFlow(host="www.google.com"))

    assert len(published) == 3
    hosts = {p.host for p in published}
    assert hosts == {
        "fctv33hd.fit",
        "adair.sworfa.kdns.fr",
        "seg.adair.sworfa.kdns.fr",
    }


def test_addon_policy_changes_are_picked_up_live() -> None:
    """El addon lee la policy en cada flow: si la mutamos, el siguiente
    flow ya ve el cambio sin reiniciar nada. Esto es lo que hace que
    el toggle de modo en la UI sea instantáneo."""
    bus = EventBus()
    published: list[HttpFlowCaptured] = []
    bus.subscribe(HttpFlowCaptured, lambda e: published.append(e))

    policy = CapturePolicy(mode=CaptureMode.ALL)
    addon = CaptureAddon(bus, policy)

    # Modo ALL: pasan todos
    addon.response(_FakeFlow(host="github.com"))
    assert len(published) == 1

    # Cambio a WHITELIST con un solo dominio permitido
    policy.mode = CaptureMode.WHITELIST
    policy.whitelisted_domains = ("fctv33hd.fit",)

    # github.com ya NO pasa
    addon.response(_FakeFlow(host="github.com"))
    # fctv33hd.fit SÍ pasa
    addon.response(_FakeFlow(host="fctv33hd.fit"))

    assert len(published) == 2
    assert published[0].host == "github.com"  # el de antes del cambio
    assert published[1].host == "fctv33hd.fit"


def test_addon_pauses_when_policy_paused() -> None:
    bus = EventBus()
    published: list[HttpFlowCaptured] = []
    bus.subscribe(HttpFlowCaptured, lambda e: published.append(e))

    policy = CapturePolicy(mode=CaptureMode.ALL, paused=True)
    addon = CaptureAddon(bus, policy)
    addon.response(_FakeFlow(host="fctv33hd.fit"))
    assert published == []


def test_addon_respects_excluded_domains_in_all_mode() -> None:
    """En modo ALL, `excluded_domains` sigue funcionando como antes:
    los hosts excluidos NO se publican al bus."""
    bus = EventBus()
    published: list[HttpFlowCaptured] = []
    bus.subscribe(HttpFlowCaptured, lambda e: published.append(e))

    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        excluded_domains=("ads.example",),
    )
    addon = CaptureAddon(bus, policy)
    addon.response(_FakeFlow(host="fctv33hd.fit"))
    addon.response(_FakeFlow(host="track.ads.example"))
    assert len(published) == 1
    assert published[0].host == "fctv33hd.fit"
