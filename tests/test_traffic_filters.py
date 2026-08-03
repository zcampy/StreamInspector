from streaminspector.gui.traffic_filters import _status_matches, _type_matches


def test_status_filter_groups_http_families() -> None:
    assert _status_matches(204, "2xx")
    assert _status_matches(404, "4xx")
    assert not _status_matches(500, "4xx")
    assert _status_matches(None, "Sin respuesta")


def test_content_type_filter_recognizes_common_mime_types() -> None:
    assert _type_matches("application/problem+json; charset=utf-8", "JSON")
    assert _type_matches("text/html", "HTML")
    assert _type_matches("application/javascript", "JavaScript")
    assert _type_matches("image/png", "Imagen")
    assert _type_matches("video/mp4", "Audio/Vídeo")
    assert _type_matches("application/pdf", "Otro")
    assert not _type_matches("application/json", "Otro")
