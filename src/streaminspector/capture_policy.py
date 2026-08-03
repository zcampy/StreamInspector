from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(slots=True)
class CapturePolicy:
    paused: bool = False
    excluded_domains: tuple[str, ...] = ()
    omit_static: bool = False

    def accepts(self, flow: HttpFlowCaptured) -> bool:
        if self.paused:
            return False
        host = (flow.host or "").lower().rstrip(".")
        if any(_domain_matches(host, pattern) for pattern in self.excluded_domains):
            return False
        if self.omit_static and _is_static(flow):
            return False
        return True


def normalize_domains(value: str) -> tuple[str, ...]:
    values: list[str] = []
    for raw in value.replace(",", "\n").splitlines():
        domain = raw.strip().lower().lstrip("*.").rstrip(".")
        if domain and domain not in values:
            values.append(domain)
    return tuple(values)


def _domain_matches(host: str, pattern: str) -> bool:
    clean = pattern.lower().lstrip("*.").rstrip(".")
    return bool(clean) and (host == clean or host.endswith(f".{clean}"))


def _is_static(flow: HttpFlowCaptured) -> bool:
    content_type = (flow.content_type or "").split(";", 1)[0].strip().lower()
    if content_type in STATIC_TYPES or content_type.startswith(STATIC_PREFIXES):
        return True
    path = (flow.path or "").split("?", 1)[0].lower()
    return path.endswith(STATIC_SUFFIXES)
