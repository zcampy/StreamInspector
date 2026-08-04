from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import RLock, Thread

from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster

from streaminspector.capture_policy import CapturePolicy
from streaminspector.core.events import (
    EventBus,
    ProxyError,
    ProxyStartRequested,
    ProxyStateChanged,
    ProxyStopRequested,
    StatusMessage,
)
from streaminspector.proxy.addon import CaptureAddon

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _ProxyEndpoint:
    host: str = "127.0.0.1"
    port: int = 8080


class ProxyService:
    """Run mitmproxy in its own asyncio loop and expose lifecycle through events.

    El host y el puerto llegan por evento (`ProxyStartRequested`) o se aplican
    vía `start(host, port)`. La UI los persiste en `QSettings`; este servicio
    no consulta ni pydantic ni QSettings: una sola fuente de verdad arriba,
    una sola conexión aquí.

    Comparte un `CapturePolicy` con la UI: cuando la UI cambia el modo
    (ALL/WHITELIST) o edita la whitelist, el filtro del addon se actualiza
    "en vivo" porque la policy es el mismo objeto mutable. Esto permite
    que el filtrado ocurra a nivel de addon (no en storage) y los datos
    sensibles nunca lleguen al EventBus.
    """

    def __init__(self, event_bus: EventBus, policy: CapturePolicy) -> None:
        self._event_bus = event_bus
        self._policy = policy
        self._endpoint = _ProxyEndpoint()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._master: DumpMaster | None = None
        self._lock = RLock()
        self._event_bus.subscribe(ProxyStartRequested, self._on_start_requested)
        self._event_bus.subscribe(ProxyStopRequested, self._on_stop_requested)

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def endpoint(self) -> tuple[str, int]:
        with self._lock:
            return self._endpoint.host, self._endpoint.port

    def start(self, host: str | None = None, port: int | None = None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if host is not None:
                self._endpoint.host = host
            if port is not None:
                self._endpoint.port = port
            self._thread = Thread(
                target=self._thread_main,
                name="streaminspector-proxy",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            master = self._master
        if loop is not None and master is not None and loop.is_running():
            loop.call_soon_threadsafe(master.shutdown)

    def close(self) -> None:
        self.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _on_start_requested(self, event: ProxyStartRequested) -> None:
        self.start(event.host, event.port)

    def _on_stop_requested(self, _event: ProxyStopRequested) -> None:
        self.stop()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
            host, port = self._endpoint.host, self._endpoint.port

        try:
            loop.run_until_complete(self._run_proxy())
        except Exception as exc:
            LOGGER.exception("Proxy engine failed")
            self._event_bus.publish(ProxyError(message=str(exc)))
            self._event_bus.publish(StatusMessage(message=f"Error del proxy: {exc}", level="error"))
        finally:
            with self._lock:
                self._master = None
                self._loop = None
                self._thread = None
            self._event_bus.publish(
                ProxyStateChanged(
                    running=False,
                    host=host,
                    port=port,
                )
            )
            loop.close()

    async def _run_proxy(self) -> None:
        with self._lock:
            host, port = self._endpoint.host, self._endpoint.port

        proxy_options = options.Options(
            listen_host=host,
            listen_port=port,
        )
        master = DumpMaster(proxy_options, with_termlog=False, with_dumper=False)
        master.addons.add(CaptureAddon(self._event_bus, self._policy))
        with self._lock:
            self._master = master

        self._event_bus.publish(
            ProxyStateChanged(
                running=True,
                host=host,
                port=port,
            )
        )
        self._event_bus.publish(
            StatusMessage(message=f"Proxy escuchando en {host}:{port}")
        )
        await master.run()
