import pytest

from app.services import extractor
from app.services.extractor import InvalidURLError, extract_page, validate_url
from app.schemas import ExtractionResult


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


def test_youtube_uses_metadata_without_downloading_watch_page(monkeypatch):
    monkeypatch.setattr(extractor, "validate_url", lambda url: url)
    monkeypatch.setattr(
        extractor,
        "_youtube_metadata",
        lambda url: ExtractionResult(
            "A video title",
            "## 视频信息\n\n- 来源：[在 YouTube 观看](https://youtube.com/watch?v=1)",
        ),
    )

    def unexpected_download(_: str):
        raise AssertionError("YouTube watch page should not be downloaded after oEmbed succeeds")

    monkeypatch.setattr(extractor, "_download_html", unexpected_download)
    result = extract_page("https://www.youtube.com/watch?v=1")

    assert result.status == "success"
    assert result.title == "A video title"
    assert "YouTube" in result.markdown_content


def test_extract_page_falls_back_to_metadata_description(monkeypatch):
    class Metadata:
        title = "Dynamic page"
        description = "A useful description available without article text."

    monkeypatch.setattr(extractor, "validate_url", lambda url: url)
    monkeypatch.setattr(extractor, "_youtube_metadata", lambda url: None)
    monkeypatch.setattr(
        extractor,
        "_download_html",
        lambda url: ("<html><head></head><body></body></html>", url),
    )
    monkeypatch.setattr(extractor.trafilatura, "extract_metadata", lambda html: Metadata())
    monkeypatch.setattr(extractor.trafilatura, "extract", lambda *args, **kwargs: None)

    result = extract_page("https://example.com/dynamic")

    assert result.status == "success"
    assert result.title == "Dynamic page"
    assert "useful description" in result.markdown_content
