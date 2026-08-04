from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37
REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
DEFAULT_BYPASS = "<local>;localhost;127.*"
MITMPROXY_CERT_DIR = Path.home() / ".mitmproxy"
MITMPROXY_CERT_FILE = MITMPROXY_CERT_DIR / "mitmproxy-ca-cert.cer"
MITMPROXY_CERT_SUBJECT_HINT = "mitmproxy"


@dataclass(frozen=True, slots=True)
class SystemProxySnapshot:
    enabled: int
    server: str
    bypass: str


def system_proxy_supported() -> bool:
    return os.name == "nt"


def enable_system_proxy(host: str, port: int) -> SystemProxySnapshot:
    if not system_proxy_supported():
        raise RuntimeError("La configuración automática del proxy solo está disponible en Windows.")

    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        REGISTRY_PATH,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        snapshot = SystemProxySnapshot(
            enabled=_read_registry_value(key, "ProxyEnable", 0),
            server=_read_registry_value(key, "ProxyServer", ""),
            bypass=_read_registry_value(key, "ProxyOverride", ""),
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, DEFAULT_BYPASS)
    _notify_windows()
    return snapshot


def restore_system_proxy(snapshot: SystemProxySnapshot) -> None:
    if not system_proxy_supported():
        return

    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        REGISTRY_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, snapshot.enabled)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, snapshot.server)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, snapshot.bypass)
    _notify_windows()


def _read_registry_value(key: object, name: str, default: int | str) -> int | str:
    import winreg

    try:
        return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return default


def _notify_windows() -> None:
    internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
    internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
    internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)


# --- CA certificate auto-install ---------------------------------------------
# mitmproxy genera su CA en `~/.mitmproxy/mitmproxy-ca-cert.cer` al arrancar el
# proxy. Para que el navegador (y otras apps que usen el cert store del usuario)
# confíen en él hay que importarlo en `Cert:\CurrentUser\Root`. Esto NO requiere
# admin porque es el store del usuario actual.


@dataclass(frozen=True, slots=True)
class CaInstallResult:
    """Resultado del intento de auto-instalación del CA de mitmproxy."""

    installed: bool
    already_present: bool
    cert_path: Path
    detail: str = ""


def ca_certificate_path() -> Path:
    """Ruta al `.cer` que mitmproxy genera al arrancar el proxy."""
    return MITMPROXY_CERT_FILE


def ca_certificate_generated() -> bool:
    """True si mitmproxy ya generó el CA en disco."""
    return MITMPROXY_CERT_FILE.exists()


def ca_certificate_installed() -> bool:
    """True si el CA de mitmproxy está en el store `Root` del usuario actual.

    Usa `certutil -user -store Root` y busca la cadena `mitmproxy` en la salida.
    """
    if not system_proxy_supported():
        return False
    if not MITMPROXY_CERT_FILE.exists():
        return False
    certutil = shutil.which("certutil")
    if certutil is None:
        return False
    try:
        completed = subprocess.run(
            [certutil, "-user", "-store", "Root"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return MITMPROXY_CERT_SUBJECT_HINT in completed.stdout.lower()


def install_ca_certificate() -> CaInstallResult:
    """Instala el CA de mitmproxy en el store del usuario actual.

    No hace nada fuera de Windows o si el cert aún no fue generado por
    mitmproxy. Devuelve un `CaInstallResult` con el detalle para mostrar en
    la status bar de la app.
    """
    if not system_proxy_supported():
        return CaInstallResult(
            installed=False,
            already_present=False,
            cert_path=MITMPROXY_CERT_FILE,
            detail="La instalación automática del CA solo está disponible en Windows.",
        )
    if not MITMPROXY_CERT_FILE.exists():
        return CaInstallResult(
            installed=False,
            already_present=False,
            cert_path=MITMPROXY_CERT_FILE,
            detail="mitmproxy aún no ha generado el certificado (.cer no existe).",
        )
    if ca_certificate_installed():
        return CaInstallResult(
            installed=False,
            already_present=True,
            cert_path=MITMPROXY_CERT_FILE,
        )
    certutil = shutil.which("certutil")
    if certutil is None:
        return CaInstallResult(
            installed=False,
            already_present=False,
            cert_path=MITMPROXY_CERT_FILE,
            detail="certutil no está disponible en PATH.",
        )
    try:
        completed = subprocess.run(
            [certutil, "-user", "-addstore", "Root", str(MITMPROXY_CERT_FILE)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CaInstallResult(
            installed=False,
            already_present=False,
            cert_path=MITMPROXY_CERT_FILE,
            detail=f"certutil falló: {exc}",
        )
    if completed.returncode != 0:
        return CaInstallResult(
            installed=False,
            already_present=False,
            cert_path=MITMPROXY_CERT_FILE,
            detail=(completed.stderr or completed.stdout or "").strip()
            or f"certutil salió con código {completed.returncode}",
        )
    return CaInstallResult(
        installed=True,
        already_present=False,
        cert_path=MITMPROXY_CERT_FILE,
    )
