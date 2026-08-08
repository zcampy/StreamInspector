from streaminspector.telegram_source_resolver import (
    extract_external_urls,
    football_page_from_site,
)


def test_extract_external_urls_prefers_newest_message_and_ignores_telegram_links() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      <a href="https://old.example/es">Anterior</a>
    </div>
    <div class="tgme_widget_message_wrap">
      <a href="https://t.me/juegoloco77_k/1740">Telegram</a>
      <a href="https://www.current.example/es">Web actual</a>
    </div>
    """

    assert extract_external_urls(html)[:2] == [
        "https://www.current.example/es",
        "https://old.example/es",
    ]


def test_extract_external_urls_reads_plain_text_urls() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      Sitio actual: https://www.current.example/es
    </div>
    """

    assert extract_external_urls(html) == ["https://www.current.example/es"]


def test_football_page_from_spanish_root() -> None:
    assert football_page_from_site("https://www.current.example/es") == (
        "https://www.current.example/es/football.html"
    )


def test_football_page_from_home_page() -> None:
    assert football_page_from_site("https://www.current.example/") == (
        "https://www.current.example/es/football.html"
    )
