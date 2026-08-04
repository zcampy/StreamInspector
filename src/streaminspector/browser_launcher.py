"""Lanzador de navegador dedicado para captura aislada.

Cuando el usuario quiere capturar tráfico sin que el resto del sistema
(GitHub Desktop, ChatGPT, telemetría, etc.) pase por el proxy, este módulo
arranca una instancia NUEVA de un navegador con dos flags clave:

  --proxy-server=http://127.0.0.1:8080    → usa el proxy de StreamInspector
  --user-data-dir=<directorio temporal>   → perfil limpio, sin cookies/
                                              sesiones del navegador normal

El resto del sistema NO se ve afectado porque el flag va por proceso, no
por configuración global de Windows. La instancia nueva se mata al
detener la captura o al cerrar la app.

Actualmente soporta Edge y Chrome (Chromium). Firefox requeriría
manipular prefs.js y se queda fuera del primer corte.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class BrowserKind(StrEnum):
    EDGE = "edge"
    CHROME = "chrome"
    FIREFOX = "firefox"


# Rutas conocidas de instalación de Edge/Chrome en Windows. Edge viene
# preinstalado en Windows 10/11 así que suele estar. Chrome solo si el
# usuario lo ha instalado.
_DEFAULT_BROWSER_PATHS: dict[BrowserKind, tuple[str, ...]] = {
    BrowserKind.EDGE: (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ),
    BrowserKind.CHROME: (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ),
    BrowserKind.FIREFOX: (
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ),
}

# Argumentos comunes para una instancia de Chromium "limpia y silenciosa"
# que no moleste al usuario con diálogos de primer arranque ni con
# notificaciones.
_CHROMIUM_COMMON_ARGS: tuple[str, ...] = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-features=Translate,InfiniteSessionRestore",
)


@dataclass(frozen=True, slots=True)
class InstalledBrowser:
    """Una instalación de navegador detectada en el sistema."""

    kind: BrowserKind
    path: Path

    @property
    def name(self) -> str:
        return {
            BrowserKind.EDGE: "Microsoft Edge",
            BrowserKind.CHROME: "Google Chrome",
            BrowserKind.FIREFOX: "Mozilla Firefox",
        }.get(self.kind, self.kind.value.capitalize())


@dataclass
class LaunchedBrowser:
    """Handle a una instancia de navegador lanzada para captura.

    `process` es el `subprocess.Popen`; `profile_dir` es el directorio
    temporal de perfil (se borra al cerrar); `ignore_cert_errors` indica
    si se usó `--ignore-certificate-errors` (porque el CA de mitmproxy
    no estaba instalado en el cert store del usuario).
    """

    browser: InstalledBrowser
    process: subprocess.Popen
    profile_dir: Path | None = None
    ignore_cert_errors: bool = True
    pid: int = field(init=False)

    def __post_init__(self) -> None:
        self.pid = self.process.pid

    @property
    def is_alive(self) -> bool:
        """True si el proceso sigue vivo.

        `poll()` devuelve `None` mientras el proceso corre y el código
        de salida cuando termina. Importante: NO usar `wait()` ni
        `communicate()` porque bloquearía la UI.
        """
        return self.process.poll() is None

    def close(self, timeout: float = 3.0) -> bool:
        """Mata el proceso y limpia el perfil temporal.

        Devuelve True si el proceso estaba vivo y se terminó OK.
        """
        was_alive = self.is_alive
        if was_alive:
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=timeout)
            except OSError:
                # El proceso ya murió entre el check y el terminate.
                pass
        if self.profile_dir is not None:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            self.profile_dir = None
        return was_alive


def find_browsers(
    paths: dict[BrowserKind, tuple[str, ...]] | None = None,
) -> list[InstalledBrowser]:
    """Detecta los navegadores instalados en el sistema.

    `paths` permite sobreescribir las rutas a comprobar (útil para tests
    con monkeypatch). Si no se pasa, se usan las rutas por defecto
    `_DEFAULT_BROWSER_PATHS` y, como fallback, `shutil.which` para
    encontrar binarios en el PATH.

    El orden de la lista es el de aparición: Edge primero (suele estar
    en Windows), luego Chrome, luego Firefox. El primer elemento es el
    candidato por defecto para "Abrir navegador dedicado para captura".
    """
    found: list[InstalledBrowser] = []
    seen_paths: set[Path] = set()
    candidates = paths if paths is not None else _DEFAULT_BROWSER_PATHS
    for kind, raw_paths in candidates.items():
        for raw in raw_paths:
            expanded = os.path.expandvars(raw)
            p = Path(expanded)
            if p in seen_paths:
                continue
            if p.is_file():
                found.append(InstalledBrowser(kind=kind, path=p))
                seen_paths.add(p)
    # Fallback: buscar el binario en PATH
    for kind, exe_name in (
        (BrowserKind.EDGE, "msedge.exe"),
        (BrowserKind.CHROME, "chrome.exe"),
        (BrowserKind.FIREFOX, "firefox.exe"),
    ):
        located = shutil.which(exe_name)
        if located is None:
            continue
        p = Path(located)
        if p in seen_paths:
            continue
        found.append(InstalledBrowser(kind=kind, path=p))
        seen_paths.add(p)
    return found


def build_proxy_args(
    kind: BrowserKind,
    host: str,
    port: int,
    profile_dir: Path,
    ignore_cert_errors: bool = True,
) -> list[str]:
    """Devuelve los argumentos CLI para arrancar una instancia de
    navegador apuntando al proxy de StreamInspector.

    Función pura (sin subprocess) para poder testearla sin lanzar nada.
    """
    if kind is BrowserKind.FIREFOX:
        # Firefox necesita prefs.js y no soporta --proxy-server; por
        # ahora no soportamos Firefox en el launcher. La excepción
        # hace explícito el motivo en lugar de fallar silenciosamente.
        raise NotImplementedError(
            "Firefox aún no está soportado en el launcher. "
            "Usa Edge o Chrome."
        )
    args: list[str] = [
        f"--proxy-server=http://{host}:{port}",
        f"--user-data-dir={profile_dir}",
        *_CHROMIUM_COMMON_ARGS,
    ]
    if ignore_cert_errors:
        # Sin esto, el navegador muestra "Su conexión no es privada"
        # para CADA petición HTTPS porque el CA de mitmproxy no es
        # de confianza. El flag NO es ideal (desactiva validación
        # de TLS) pero es exactamente lo que un proxy de debug hace.
        # Si el usuario tiene el CA instalado en el cert store del
        # usuario, podemos saltarnos este flag y validar TLS normal.
        args.append("--ignore-certificate-errors")
    return args


def launch_browser(
    browser: InstalledBrowser,
    host: str,
    port: int,
    *,
    ignore_cert_errors: bool = True,
    profile_dir: Path | None = None,
    cleanup_profile: bool = True,
) -> LaunchedBrowser:
    """Lanza una instancia nueva del navegador con el proxy configurado.

    - `ignore_cert_errors`: True si el CA de mitmproxy NO está instalado
      en el cert store del usuario. El flag `--ignore-certificate-errors`
      evita los diálogos de "Su conexión no es privada" a cambio de
      desactivar la validación TLS.
    - `profile_dir`: directorio para el perfil de usuario. Si no se
      pasa, se crea uno temporal (se borra al cerrar la instancia).
    - `cleanup_profile`: si True, borra el profile_dir al cerrar. False
      para inspeccionar manualmente.
    """
    if profile_dir is None:
        profile_dir = Path(tempfile.mkdtemp(prefix="streaminspector-browser-"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = build_proxy_args(
        browser.kind, host, port, profile_dir, ignore_cert_errors
    )
    # CREATE_NEW_PROCESS_GROUP: para poder matar el árbol de procesos
    # con terminate() sin afectar a otros navegadores que el usuario
    # pueda tener abiertos.
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    process = subprocess.Popen(  # noqa: S603
        [str(browser.path), *args],
        creationflags=creationflags,
        # Si no redirigimos stdout/stderr en Windows, el navegador
        # abre una consola extra.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # No bloqueamos el proceso padre: el navegador debe correr
        # mientras la app sigue.
        close_fds=True,
    )
    return LaunchedBrowser(
        browser=browser,
        process=process,
        profile_dir=profile_dir if cleanup_profile else None,
        ignore_cert_errors=ignore_cert_errors,
    )


def default_browser() -> InstalledBrowser | None:
    """Devuelve el primer navegador detectado, o None si no hay ninguno."""
    found = find_browsers()
    return found[0] if found else None
