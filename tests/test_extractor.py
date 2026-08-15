import pytest

from app.services import extractor
from app.services.extractor import InvalidURLError, extract_page, validate_url


def test_validate_url_rejects_unsupported_scheme():
    with pytest.raises(InvalidURLError):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_loopback():
    with pytest.raises(InvalidURLError):
        validate_url("http://127.0.0.1/admin")


def test_validate_url_allows_proxy_fake_ip_for_domain(monkeypatch):
    monkeypatch.setattr(
        extractor.socket,
        "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("198.18.0.8", 0))],
    )

    assert validate_url("https://programmercarl.com/") == "https://programmercarl.com/"


def test_validate_url_rejects_direct_proxy_fake_ip():
    with pytest.raises(InvalidURLError):
        validate_url("http://198.18.0.8/")


def test_extract_page_returns_markdown(monkeypatch):
    html = """
    <html><head><title>A useful article</title></head>
    <body><article><h1>A useful article</h1><p>This is the main content with enough words to extract.</p></article></body></html>
    """
    monkeypatch.setattr(extractor, "validate_url", lambda url: url)
    monkeypatch.setattr(extractor, "_download_html", lambda url: (html, url))

    result = extract_page("https://example.com/article")

    assert result.status == "success"
    assert result.title == "A useful article"
    assert "main content" in result.markdown_content


def test_extract_page_keeps_bookmark_data_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(extractor, "validate_url", lambda url: url)

    def fail(_: str):
        raise extractor.FetchError("request timed out")

    monkeypatch.setattr(extractor, "_download_html", fail)
    result = extract_page("https://example.com/article")

    assert result.status == "fetch_failed"
    assert result.title == "example.com"
    assert result.markdown_content == ""
    assert result.error_message == "request timed out"
