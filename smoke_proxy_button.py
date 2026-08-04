"""Smoke test del botón ON/OFF y del cert auto-install."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QSettings
from streaminspector import __version__

settings = QSettings("StreamInspector", "StreamInspector")
settings.setValue(f"onboarding/{__version__}", True)
settings.setValue("startup_notice/0.1.0a19", True)

from PySide6.QtWidgets import QApplication
from unittest.mock import patch

app = QApplication([])

from streaminspector.core.events import EventBus, ProxyStateChanged
from streaminspector.storage import StorageService
from streaminspector.gui.deep_search_window import DeepSearchWindow
import tempfile, pathlib

with tempfile.TemporaryDirectory() as tmp:
    bus = EventBus()
    storage = StorageService(bus, pathlib.Path(tmp) / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])

    print(f"[1] Initial: text={win.proxy_button.text()!r} checked={win.proxy_button.isChecked()}")

    # Simulate proxy starting (mock para no tocar el registry real)
    with patch("streaminspector.gui.proxy_window.enable_system_proxy", return_value=None), \
         patch("streaminspector.system_proxy.ca_certificate_generated", return_value=True), \
         patch("streaminspector.system_proxy.ca_certificate_installed", return_value=True):
        bus.publish(ProxyStateChanged(running=True, host="127.0.0.1", port=8080))
    print(f"[2] Running: text={win.proxy_button.text()!r} checked={win.proxy_button.isChecked()}")

    # Simulate proxy stopping
    bus.publish(ProxyStateChanged(running=False, host="127.0.0.1", port=8080))
    print(f"[3] Stopped: text={win.proxy_button.text()!r} checked={win.proxy_button.isChecked()}")

    # Verify cert auto-install flow with a mock for install_ca_certificate
    from streaminspector.system_proxy import CaInstallResult
    with patch("streaminspector.system_proxy.ca_certificate_generated", return_value=True), \
         patch("streaminspector.system_proxy.ca_certificate_installed", return_value=False), \
         patch(
             "streaminspector.system_proxy.install_ca_certificate",
             return_value=CaInstallResult(installed=True, already_present=False, cert_path=pathlib.Path("dummy")),
         ):
        messages = []
        bus.subscribe(type(messages), lambda e: None)  # noop to ensure type stability
        # capture status messages
        from streaminspector.core.events import StatusMessage
        captured = []
        bus.subscribe(StatusMessage, lambda e: captured.append(e))
        bus.publish(ProxyStateChanged(running=True, host="127.0.0.1", port=8080))
        win._try_auto_install_ca_certificate()
        install_msgs = [e.message for e in captured if "Certificado" in e.message]
        print(f"[4] Cert install msgs: {install_msgs}")

    storage.close()
print("OK")
