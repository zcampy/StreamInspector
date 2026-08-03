from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
STAMP_FILE = VENV_DIR / ".streaminspector-install"
PROJECT_FILE = ROOT / "pyproject.toml"
MIN_PYTHON = (3, 12)


def _python_in_venv() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _project_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(PROJECT_FILE.read_bytes())
    digest.update(f"{sys.version_info.major}.{sys.version_info.minor}".encode())
    return digest.hexdigest()


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, check=check, text=True)


def _ensure_supported_python() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(map(str, MIN_PYTHON))
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise SystemExit(
            f"StreamInspector necesita Python {required} o superior; instalado: {current}."
        )


def _ensure_environment() -> Path:
    python = _python_in_venv()
    if not python.exists():
        print("[StreamInspector] Creando entorno virtual...")
        _run([sys.executable, "-m", "venv", str(VENV_DIR)])

    fingerprint = _project_fingerprint()
    installed_fingerprint = STAMP_FILE.read_text(encoding="utf-8") if STAMP_FILE.exists() else ""
    if installed_fingerprint != fingerprint:
        print("[StreamInspector] Instalando o actualizando dependencias...")
        _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
        _run([str(python), "-m", "pip", "install", "-e", "."])
        STAMP_FILE.write_text(fingerprint, encoding="utf-8")

    return python


def main() -> int:
    _ensure_supported_python()
    python = _ensure_environment()
    print("[StreamInspector] Iniciando aplicación...")
    completed = _run([str(python), "-m", "streaminspector.main"], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
