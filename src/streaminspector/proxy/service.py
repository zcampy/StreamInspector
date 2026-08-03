from __future__ import annotations

import asyncio
import logging
from threading import RLock, Thread

from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster

from streaminspector.core.config import ProxySettings
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


class ProxyService:
    """Run mitmproxy in its own asyncio loop and expose lifecycle through events."""

    def __init__(self, event_bus: EventBus, settings: ProxySettings) -> None:
        self._event_bus = event_bus
        self._settings = settings
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

    def start(self, host: str | None = None, port: int | None = None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if host is not None:
                self._settings.host = host
            if port is not None:
                self._settings.port = port
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
                    host=self._settings.host,
                    port=self._settings.port,
                )
            )
            loop.close()

    async def _run_proxy(self) -> None:
        proxy_options = options.Options(
            listen_host=self._settings.host,
            listen_port=self._settings.port,
        )
        master = DumpMaster(proxy_options, with_termlog=False, with_dumper=False)
        master.addons.add(CaptureAddon(self._event_bus))
        with self._lock:
            self._master = master

        self._event_bus.publish(
            ProxyStateChanged(
                running=True,
                host=self._settings.host,
                port=self._settings.port,
            )
        )
        self._event_bus.publish(
            StatusMessage(
                message=f"Proxy escuchando en {self._settings.host}:{self._settings.port}"
            )
        )
        await master.run()
