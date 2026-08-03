from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37
REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
DEFAULT_BYPASS = "<local>;localhost;127.*"


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
