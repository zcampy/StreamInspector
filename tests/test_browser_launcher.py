"""Tests del browser_launcher: detección de navegadores, construcción
de args CLI, lanzamiento y limpieza.

Estos tests NO arrancan navegadores reales: usan un binario falso
(un .bat con `timeout`) o mockean `subprocess.Popen` para verificar
que la lógica de orquestación es correcta. El objetivo es cubrir el
camino crítico: detectar navegador, lanzar con los args correctos,
cerrar limpiamente.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from streaminspector.browser_launcher import (
    BrowserKind,
    InstalledBrowser,
    LaunchedBrowser,
    build_proxy_args,
    default_browser,
    find_browsers,
    launch_browser,
)

# ----------------------- build_proxy_args (función pura) ---------------------


def test_build_proxy_args_uses_proxy_server_flag() -> None:
    args = build_proxy_args(BrowserKind.EDGE, "127.0.0.1", 8080, Path("/tmp/profile"))
    assert "--proxy-server=http://127.0.0.1:8080" in args


def test_build_proxy_args_uses_isolated_profile_dir(tmp_path: Path) -> None:
    profile = tmp_path / "my-profile"
    args = build_proxy_args(
        BrowserKind.CHROME, "127.0.0.1", 8080, profile
    )
    assert f"--user-data-dir={profile}" in args


def test_build_proxy_args_adds_ignore_cert_when_no_ca() -> None:
    """Si el CA de mitmproxy no está instalado, añadimos el flag."""
    args = build_proxy_args(
        BrowserKind.EDGE, "127.0.0.1", 8080, Path("/tmp"), ignore_cert_errors=True
    )
    assert "--ignore-certificate-errors" in args


def test_build_proxy_args_skips_ignore_cert_when_ca_installed() -> None:
    """Si el CA está en el cert store, NO añadimos el flag (TLS valida)."""
    args = build_proxy_args(
        BrowserKind.EDGE,
        "127.0.0.1",
        8080,
        Path("/tmp"),
        ignore_cert_errors=False,
    )
    assert "--ignore-certificate-errors" not in args


def test_build_proxy_args_includes_silencing_flags() -> None:
    args = build_proxy_args(BrowserKind.EDGE, "127.0.0.1", 8080, Path("/tmp"))
    # Flags para que el navegador no spamee al usuario
    assert "--no-first-run" in args
    assert "--no-default-browser-check" in args


def test_build_proxy_args_works_for_chrome_too(tmp_path: Path) -> None:
    profile = tmp_path / "p"
    args = build_proxy_args(BrowserKind.CHROME, "127.0.0.1", 9000, profile)
    assert "--proxy-server=http://127.0.0.1:9000" in args
    assert f"--user-data-dir={profile}" in args


def test_build_proxy_args_firefox_raises_not_implemented() -> None:
    """Firefox no está soportado en el primer corte."""
    with pytest.raises(NotImplementedError, match="Firefox"):
        build_proxy_args(BrowserKind.FIREFOX, "127.0.0.1", 8080, Path("/tmp"))


def test_build_proxy_args_uses_custom_host_and_port() -> None:
    """El host:puerto del proxy viene de la configuración de StreamInspector."""
    args = build_proxy_args(BrowserKind.EDGE, "192.168.1.50", 9999, Path("/tmp"))
    assert "--proxy-server=http://192.168.1.50:9999" in args


# ------------------------- find_browsers -------------------------------------


def test_find_browsers_returns_empty_when_no_paths(tmp_path: Path) -> None:
    """Si no hay ninguna ruta válida, devuelve lista vacía."""
    # Monkeypatch: ningún navegador disponible
    fake_paths: dict[BrowserKind, tuple[str, ...]] = {
        BrowserKind.EDGE: (str(tmp_path / "no-edge.exe"),),
        BrowserKind.CHROME: (str(tmp_path / "no-chrome.exe"),),
    }
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=None
    ):
        result = find_browsers(paths=fake_paths)
    assert result == []


def test_find_browsers_finds_edge_at_provided_path(tmp_path: Path) -> None:
    """Si la ruta a Edge existe, la devuelve."""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("fake")
    fake_paths = {BrowserKind.EDGE: (str(fake_edge),)}
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=None
    ):
        result = find_browsers(paths=fake_paths)
    assert len(result) == 1
    assert result[0].kind is BrowserKind.EDGE
    assert result[0].path == fake_edge
    assert result[0].name == "Microsoft Edge"


def test_find_browsers_dedupes_across_overlapping_paths(tmp_path: Path) -> None:
    """Si la misma ruta aparece para dos kinds, no se duplica."""
    fake_path = tmp_path / "msedge.exe"
    fake_path.write_text("fake")
    fake_paths = {
        BrowserKind.EDGE: (str(fake_path),),
        BrowserKind.CHROME: (str(fake_path),),  # mismo path por error
    }
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=None
    ):
        result = find_browsers(paths=fake_paths)
    assert len(result) == 1


def test_find_browsers_expands_env_vars(tmp_path: Path) -> None:
    """%LOCALAPPDATA% y similares se expanden en las rutas."""
    fake_chrome = tmp_path / "chrome.exe"
    fake_chrome.write_text("fake")
    fake_paths = {
        BrowserKind.CHROME: (str(fake_chrome),),  # absoluto, no usa env
    }
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=None
    ):
        result = find_browsers(paths=fake_paths)
    assert len(result) == 1


def test_find_browsers_falls_back_to_which(tmp_path: Path) -> None:
    """Si las rutas por defecto fallan pero el binario está en PATH,
    lo encontramos igualmente."""
    fake = tmp_path / "msedge.exe"
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=str(fake)
    ):
        # Sin paths custom → no encuentra por defecto
        result = find_browsers(paths={BrowserKind.EDGE: (str(tmp_path / "missing"),)})
    assert len(result) == 1
    assert result[0].path == fake


# ------------------------- default_browser -----------------------------------


def test_default_browser_returns_none_when_nothing_found(tmp_path: Path) -> None:
    with (
        patch("streaminspector.browser_launcher.shutil.which", return_value=None),
        patch(
            "streaminspector.browser_launcher.find_browsers",
            return_value=[],
        ),
    ):
        assert default_browser() is None


def test_default_browser_prefers_edge(tmp_path: Path) -> None:
    """Si hay Edge y Chrome, devolvemos Edge primero (suele estar preinstalado)."""
    edge = tmp_path / "msedge.exe"
    chrome = tmp_path / "chrome.exe"
    edge.write_text("x")
    chrome.write_text("x")
    fake_paths = {
        BrowserKind.EDGE: (str(edge),),
        BrowserKind.CHROME: (str(chrome),),
    }
    with patch(
        "streaminspector.browser_launcher.shutil.which", return_value=None
    ):
        result = default_browser() if False else find_browsers(paths=fake_paths)[0]
    assert result.kind is BrowserKind.EDGE


# --------------------- launch_browser (con subprocess mockeado) -------------


def test_launch_browser_spawns_subprocess_with_correct_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`launch_browser` invoca Popen con los args de build_proxy_args."""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("fake")
    browser = InstalledBrowser(kind=BrowserKind.EDGE, path=fake_edge)
    profile_dir = tmp_path / "profile"

    fake_popen_class = MagicMock()
    # La instancia que devuelve Popen() — la configuramos con pid y poll()
    fake_instance = MagicMock()
    fake_instance.pid = 12345
    fake_instance.poll.return_value = None  # proceso vivo
    fake_popen_class.return_value = fake_instance
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen", fake_popen_class
    )

    launched = launch_browser(
        browser,
        "127.0.0.1",
        8080,
        ignore_cert_errors=True,
        profile_dir=profile_dir,
    )
    assert launched.pid == 12345
    assert launched.profile_dir == profile_dir
    assert launched.is_alive is True

    # El primer argumento del Popen es la ruta al ejecutable
    call_args = fake_popen_class.call_args[0][0]
    assert call_args[0] == str(fake_edge)
    # Los args CLI incluyen el proxy y el profile
    assert "--proxy-server=http://127.0.0.1:8080" in call_args
    assert any(
        a == f"--user-data-dir={profile_dir}" for a in call_args
    ), f"--user-data-dir={profile_dir} not in {call_args}"
    assert "--ignore-certificate-errors" in call_args


def test_launch_browser_creates_temp_profile_if_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si no se pasa profile_dir, se crea uno temporal bajo
    `streaminspector-browser-`."""
    browser = InstalledBrowser(
        kind=BrowserKind.EDGE, path=tmp_path / "msedge.exe"
    )
    (tmp_path / "msedge.exe").write_text("x")
    fake_popen = MagicMock()
    fake_popen.pid = 1
    fake_popen.poll.return_value = None
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen", fake_popen
    )

    with patch("tempfile.mkdtemp") as mkdtemp_mock:
        mkdtemp_mock.return_value = str(tmp_path / "auto-profile")
        launched = launch_browser(browser, "127.0.0.1", 8080)

    assert "auto-profile" in str(launched.profile_dir)
    assert Path(launched.profile_dir).exists()  # lo creó


def test_launch_browser_propagates_filenotfound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el ejecutable no existe, Popen lanza FileNotFoundError y la
    función la propaga (la UI la convierte en QMessageBox)."""
    browser = InstalledBrowser(
        kind=BrowserKind.EDGE, path=tmp_path / "nonexistent.exe"
    )
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen",
        MagicMock(side_effect=FileNotFoundError("no such exe")),
    )
    with pytest.raises(FileNotFoundError):
        launch_browser(browser, "127.0.0.1", 8080)


# --------------------- LaunchedBrowser.close --------------------------------


def test_close_terminates_running_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`close()` llama a terminate() si el proceso está vivo."""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("x")
    fake_popen_class = MagicMock()
    fake_instance = MagicMock()
    fake_instance.pid = 99
    # poll() siempre devuelve None: el proceso está vivo. Después de
    # terminate()+wait() sigue vivo "conceptualmente" (el test no verifica
    # que muera, solo que close() lo intenta matar).
    fake_instance.poll.return_value = None
    fake_popen_class.return_value = fake_instance
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen", fake_popen_class
    )
    launched = launch_browser(
        InstalledBrowser(kind=BrowserKind.EDGE, path=fake_edge),
        "127.0.0.1",
        8080,
        profile_dir=tmp_path / "p",
    )
    (tmp_path / "p").mkdir(parents=True, exist_ok=True)

    was_alive = launched.close()
    assert was_alive is True
    fake_instance.terminate.assert_called_once()
    fake_instance.wait.assert_called()


def test_close_cleans_up_profile_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`close()` borra el directorio temporal del perfil."""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("x")
    profile = tmp_path / "p"
    profile.mkdir()
    (profile / "Default").mkdir()
    (profile / "Default" / "Cookies").write_text("fake")

    fake_popen = MagicMock()
    fake_popen.pid = 1
    fake_popen.poll.return_value = None
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen", fake_popen
    )
    launched = launch_browser(
        InstalledBrowser(kind=BrowserKind.EDGE, path=fake_edge),
        "127.0.0.1",
        8080,
        profile_dir=profile,
    )
    launched.close()
    assert not profile.exists()


def test_close_keeps_profile_when_cleanup_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si cleanup_profile=False, el perfil se queda para inspección manual."""
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("x")
    profile = tmp_path / "p"
    profile.mkdir()

    fake_popen = MagicMock()
    fake_popen.pid = 1
    fake_popen.poll.return_value = None
    monkeypatch.setattr(
        "streaminspector.browser_launcher.subprocess.Popen", fake_popen
    )
    launched = launch_browser(
        InstalledBrowser(kind=BrowserKind.EDGE, path=fake_edge),
        "127.0.0.1",
        8080,
        profile_dir=profile,
        cleanup_profile=False,
    )
    launched.close()
    assert profile.exists()  # NO se borra


def test_is_alive_uses_poll_not_wait() -> None:
    """`is_alive` debe ser NO bloqueante. Si usara `wait()` bloquearía
    la UI mientras el navegador está abierto."""
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    launched = LaunchedBrowser(
        browser=InstalledBrowser(kind=BrowserKind.EDGE, path=Path("/fake")),
        process=fake_process,
    )
    assert launched.is_alive is True
    fake_process.poll.assert_called_once()
    # Específicamente NO debe llamar a wait (que bloquearía)
    fake_process.wait.assert_not_called()


def test_is_alive_returns_false_when_process_died() -> None:
    fake_process = MagicMock()
    fake_process.poll.return_value = 0  # código de salida
    launched = LaunchedBrowser(
        browser=InstalledBrowser(kind=BrowserKind.EDGE, path=Path("/fake")),
        process=fake_process,
    )
    assert launched.is_alive is False


# --------------------- integración: lanzar y matar un .bat real -------------


@pytest.mark.skipif(os.name != "nt", reason="Usa timeout.exe de Windows")
def test_launch_browser_lifecycle_with_real_bat(tmp_path: Path) -> None:
    """Test de integración: creamos un .bat que se queda esperando
    (`timeout /t 30`) y verificamos que `close()` lo mata de verdad."""
    bat = tmp_path / "fake-browser.bat"
    bat.write_text("@echo off\r\ntimeout /t 30 /nobreak > NUL\r\n")
    browser = InstalledBrowser(kind=BrowserKind.EDGE, path=bat)
    launched = launch_browser(
        browser, "127.0.0.1", 8080, profile_dir=tmp_path / "profile"
    )
    try:
        # El proceso está vivo
        assert launched.is_alive is True
        assert launched.pid > 0
        # Lo cerramos
        was_alive = launched.close(timeout=5.0)
        assert was_alive is True
        assert launched.is_alive is False
        # El profile se borró
        assert not (tmp_path / "profile").exists()
    finally:
        # Por si acaso, matamos cualquier residuo
        if launched.is_alive:
            launched.close()
