from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from streaminspector.core.events import HttpFlowCaptured

STATIC_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "font/",
)
STATIC_TYPES = {
    "text/css",
    "application/javascript",
    "text/javascript",
}
STATIC_SUFFIXES = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp3",
    ".mp4",
)


class CaptureMode(StrEnum):
    """Modo de filtrado del proxy.

    - `ALL`: captura todo lo que pase por el proxy, menos los filtros
      opcionales (`excluded_domains`, `omit_static`). Útil para debug
      puntual pero intercepta tráfico de TODAS las apps del sistema
      (GitHub Desktop, ChatGPT, telemetría, etc.).

    - `WHITELIST`: solo captura los hosts que coincidan con
      `whitelisted_domains` (cubren el dominio y sus subdominios).
      El resto del tráfico pasa por el proxy sin emitirse al EventBus,
      por lo que NO se guarda en SQLite ni queda en memoria de la app.
      Es el modo recomendado para uso normal: reduces ruido y
      minimizas el impacto en privacidad.
    """

    ALL = "all"
    WHITELIST = "whitelist"


@dataclass(slots=True)
class CapturePolicy:
    mode: CaptureMode = CaptureMode.ALL
    paused: bool = False
    excluded_domains: tuple[str, ...] = ()
    whitelisted_domains: tuple[str, ...] = ()
    omit_static: bool = False

    def accepts(self, flow: HttpFlowCaptured) -> bool:
        if self.paused:
            return False
        host = (flow.host or "").lower().rstrip(".")
        if self.mode is CaptureMode.WHITELIST and not any(
            _domain_matches(host, pattern)
            for pattern in self.whitelisted_domains
        ):
            return False
        if any(_domain_matches(host, pattern) for pattern in self.excluded_domains):
            return False
        return not (self.omit_static and _is_static(flow))


def normalize_domains(value: str) -> tuple[str, ...]:
    values: list[str] = []
    for raw in value.replace(",", "\n").splitlines():
        domain = raw.strip().lower().lstrip("*.").rstrip(".")
        if domain and domain not in values:
            values.append(domain)
    return tuple(values)


def load_capture_policy(settings) -> CapturePolicy:
    """Carga una `CapturePolicy` desde un `QSettings` (o similar con `.value`).

    Tolerante a valores ausentes o corruptos: si una clave falta, se usa
    el valor por defecto del dataclass. Pensado para que la app pueda
    arrancar aunque el usuario haya editado el registro a mano.

    Por defecto, si NO hay valor de `capture/mode` guardado, arrancamos
    en `WHITELIST` (modo seguro: el usuario solo captura lo que ha
    añadido explícitamente). Es el opuesto del dataclass default
    (`ALL`) porque en la práctica la app nunca se ha ejecutado antes y
    un usuario que abre StreamInspector por primera vez NO quiere que
    le intercepte todo el tráfico del sistema.
    """
    try:
        raw_mode = settings.value("capture/mode", None)
        if raw_mode is None or str(raw_mode) == "":
            mode = CaptureMode.WHITELIST
        else:
            mode = CaptureMode(str(raw_mode))
    except (ValueError, TypeError):
        mode = CaptureMode.WHITELIST
    return CapturePolicy(
        mode=mode,
        excluded_domains=normalize_domains(
            str(settings.value("capture/excluded_domains", ""))
        ),
        whitelisted_domains=normalize_domains(
            str(settings.value("capture/whitelisted_domains", ""))
        ),
        omit_static=bool(settings.value("capture/omit_static", False)),
    )


def save_capture_policy(settings, policy: CapturePolicy) -> None:
    """Persiste los campos serializables de la policy en `QSettings`."""
    settings.setValue("capture/mode", policy.mode.value)
    settings.setValue(
        "capture/excluded_domains", "\n".join(policy.excluded_domains)
    )
    settings.setValue(
        "capture/whitelisted_domains", "\n".join(policy.whitelisted_domains)
    )
    settings.setValue("capture/omit_static", policy.omit_static)


def _domain_matches(host: str, pattern: str) -> bool:
    clean = pattern.lower().lstrip("*.").rstrip(".")
    return bool(clean) and (host == clean or host.endswith(f".{clean}"))


def _is_static(flow: HttpFlowCaptured) -> bool:
    content_type = (flow.content_type or "").split(";", 1)[0].strip().lower()
    if content_type in STATIC_TYPES or content_type.startswith(STATIC_PREFIXES):
        return True
    path = (flow.path or "").split("?", 1)[0].lower()
    return path.endswith(STATIC_SUFFIXES)
