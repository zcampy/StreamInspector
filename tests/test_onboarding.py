from pathlib import Path

from streaminspector.gui.onboarding_dialog import diagnostic_report


def test_diagnostic_report_contains_proxy_and_data_dir(tmp_path: Path) -> None:
    report = diagnostic_report("127.0.0.1", 8080, tmp_path)

    assert "Proxy configurado: 127.0.0.1:8080" in report
    assert f"Directorio de datos: {tmp_path}" in report
