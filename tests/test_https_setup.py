from streaminspector.gui.https_setup_dialog import certificate_status


def test_certificate_status_detects_generated_certificate(tmp_path):
    present, files = certificate_status(tmp_path)
    assert present is False
    assert files == []

    certificate = tmp_path / "mitmproxy-ca-cert.cer"
    certificate.write_text("certificate", encoding="utf-8")

    present, files = certificate_status(tmp_path)
    assert present is True
    assert files == [certificate]
