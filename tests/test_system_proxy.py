"""Tests para la auto-instalación del CA de mitmproxy en el cert store de Windows.

Las pruebas son puras (no tocan certutil real) y mockean el subprocess.run
para verificar el flujo de decisión:

- cert no generado por mitmproxy  -> no hace nada
- cert generado, ya instalado     -> no hace nada
- cert generado, no instalado     -> instala
- certutil falla                  -> reporta el error
- fuera de Windows                 -> no hace nada
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

# `system_proxy` importa `winreg` solo cuando se llama, así que el módulo
# se puede cargar en cualquier plataforma. Lo testeamos con monkeypatch sobre
# `os.name` para simular Windows.
from streaminspector import system_proxy
from streaminspector.system_proxy import (
    ca_certificate_generated,
    ca_certificate_installed,
    install_ca_certificate,
    system_proxy_supported,
)


def test_system_proxy_supported_only_on_windows() -> None:
    with patch.object(system_proxy.os, "name", "nt"):
        assert system_proxy_supported() is True
    with patch.object(system_proxy.os, "name", "posix"):
        assert system_proxy_supported() is False


def test_ca_certificate_generated_false_when_missing(tmp_path: Path) -> None:
    with patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "nope.cer"):
        assert ca_certificate_generated() is False
    with patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "exists.cer"):
        tmp_path.joinpath("exists.cer").write_bytes(b"x")
        assert ca_certificate_generated() is True


def test_ca_certificate_installed_false_off_windows(tmp_path: Path) -> None:
    with (
        patch.object(system_proxy.os, "name", "posix"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "x.cer"),
    ):
        tmp_path.joinpath("x.cer").write_bytes(b"x")
        assert ca_certificate_installed() is False


def test_ca_certificate_installed_false_when_certutil_missing(tmp_path: Path) -> None:
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "x.cer"),
        patch.object(system_proxy.shutil, "which", return_value=None),
    ):
        tmp_path.joinpath("x.cer").write_bytes(b"x")
        assert ca_certificate_installed() is False


def test_ca_certificate_installed_true_when_listed_in_store(tmp_path: Path) -> None:
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "x.cer"),
        patch.object(
            system_proxy.shutil, "which", return_value="C:/Windows/System32/certutil.exe"
        ),
        patch.object(
            system_proxy.subprocess,
            "run",
            return_value=_completed(0, stdout="... mitmproxy ... ============="),
        ),
    ):
        tmp_path.joinpath("x.cer").write_bytes(b"x")
        assert ca_certificate_installed() is True


def test_ca_certificate_installed_false_when_not_listed(tmp_path: Path) -> None:
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "x.cer"),
        patch.object(system_proxy.shutil, "which", return_value="certutil"),
        patch.object(
            system_proxy.subprocess,
            "run",
            return_value=_completed(0, stdout="Some other root CA"),
        ),
    ):
        tmp_path.joinpath("x.cer").write_bytes(b"x")
        assert ca_certificate_installed() is False


def test_install_ca_certificate_off_windows(tmp_path: Path) -> None:
    with (
        patch.object(system_proxy.os, "name", "posix"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", tmp_path / "x.cer"),
    ):
        result = install_ca_certificate()
    assert result.installed is False
    assert result.already_present is False
    assert "solo está disponible en Windows" in result.detail


def test_install_ca_certificate_when_cert_not_generated(tmp_path: Path) -> None:
    missing = tmp_path / "absent.cer"
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", missing),
    ):
        result = install_ca_certificate()
    assert result.installed is False
    assert result.already_present is False
    assert "no existe" in result.detail


def test_install_ca_certificate_when_already_present(tmp_path: Path) -> None:
    cert = tmp_path / "x.cer"
    cert.write_bytes(b"x")
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", cert),
        patch.object(
            system_proxy, "ca_certificate_installed", return_value=True
        ),
    ):
        result = install_ca_certificate()
    assert result.installed is False
    assert result.already_present is True
    assert result.detail == ""


def test_install_ca_certificate_success(tmp_path: Path) -> None:
    cert = tmp_path / "x.cer"
    cert.write_bytes(b"x")
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", cert),
        patch.object(
            system_proxy, "ca_certificate_installed", return_value=False
        ),
        patch.object(system_proxy.shutil, "which", return_value="certutil"),
        patch.object(
            system_proxy.subprocess, "run", return_value=_completed(0)
        ),
    ):
        result = install_ca_certificate()
    assert result.installed is True
    assert result.already_present is False
    assert result.detail == ""


def test_install_ca_certificate_certutil_failure(tmp_path: Path) -> None:
    cert = tmp_path / "x.cer"
    cert.write_bytes(b"x")
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", cert),
        patch.object(
            system_proxy, "ca_certificate_installed", return_value=False
        ),
        patch.object(system_proxy.shutil, "which", return_value="certutil"),
        patch.object(
            system_proxy.subprocess,
            "run",
            return_value=_completed(1, stderr="Access is denied"),
        ),
    ):
        result = install_ca_certificate()
    assert result.installed is False
    assert "Access is denied" in result.detail


def test_install_ca_certificate_no_certutil(tmp_path: Path) -> None:
    cert = tmp_path / "x.cer"
    cert.write_bytes(b"x")
    with (
        patch.object(system_proxy.os, "name", "nt"),
        patch.object(system_proxy, "MITMPROXY_CERT_FILE", cert),
        patch.object(
            system_proxy, "ca_certificate_installed", return_value=False
        ),
        patch.object(system_proxy.shutil, "which", return_value=None),
    ):
        result = install_ca_certificate()
    assert result.installed is False
    assert "certutil no está disponible" in result.detail


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    """Helper: simula un `subprocess.CompletedProcess` sin lanzar procesos."""
    import subprocess

    return subprocess.CompletedProcess(
        args=["certutil"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
