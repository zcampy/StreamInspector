import pytest

from streaminspector.gui.replay_dialog import _parse_headers


def test_parse_headers_accepts_text_mapping_and_removes_transport_headers() -> None:
    headers = _parse_headers(
        '{"Content-Type": "application/json", "Host": "example.com", "X-Test": "1"}'
    )

    assert headers == {"Content-Type": "application/json", "X-Test": "1"}


def test_parse_headers_rejects_non_text_values() -> None:
    with pytest.raises(ValueError, match="texto a texto"):
        _parse_headers('{"X-Retry": 2}')


def test_parse_headers_reports_invalid_json() -> None:
    with pytest.raises(ValueError, match="JSON no válido"):
        _parse_headers("not-json")
