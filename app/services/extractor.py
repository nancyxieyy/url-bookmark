from __future__ import annotations

import ipaddress
import socket
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.schemas import ExtractionResult


USER_AGENT = "URLBookmark/1.0 (+local bookmark reader)"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class InvalidURLError(ValueError):
    """The URL is malformed or points to a network we must not access."""


class FetchError(RuntimeError):
    """The URL is valid, but its HTML could not be fetched."""


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_proxy_fake_address(address: str) -> bool:
    """Recognize the RFC 2544 range commonly used by local proxy fake-IP DNS."""
    return ipaddress.ip_address(address) in PROXY_FAKE_IP_NETWORK


def validate_url(url: str) -> str:
    candidate = url.strip()
    try:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise InvalidURLError("请输入以 http:// 或 https:// 开头的完整网址。")
        if parsed.username or parsed.password:
            raise InvalidURLError("网址不能包含用户名或密码。")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise InvalidURLError("网址端口无效。")
    except (ValueError, UnicodeError) as exc:
        raise InvalidURLError("网址格式无效。") from exc

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise InvalidURLError("出于安全考虑，不能访问本机或内网地址。")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not _is_public_address(str(literal_ip)):
        raise InvalidURLError("出于安全考虑，不能访问本机或内网地址。")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        # A syntactically valid but currently unresolvable URL is still bookmarkable.
        return candidate
    if not addresses or any(
        not _is_public_address(address) and not _is_proxy_fake_address(address)
        for address in addresses
    ):
        raise InvalidURLError("出于安全考虑，不能访问本机或内网地址。")
    return candidate


def _download_html(url: str) -> tuple[str, str]:
    current_url = url
    timeout = httpx.Timeout(8.0, connect=4.0)
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
            follow_redirects=False,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                current_url = validate_url(current_url)
                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("网页返回了无目标地址的重定向。")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        raise FetchError("目标不是 HTML 网页。")

                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise FetchError("网页内容超过 5 MB 限制。")
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    return b"".join(chunks).decode(encoding, errors="replace"), str(response.url)
            raise FetchError("网页重定向次数过多。")
    except InvalidURLError:
        raise
    except FetchError:
        raise
    except httpx.HTTPStatusError as exc:
        raise FetchError(f"网页返回 HTTP {exc.response.status_code}。") from exc
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise FetchError("连接网页失败或请求超时。") from exc
    except httpx.HTTPError as exc:
        raise FetchError("无法读取该网页。") from exc


def _fallback_title(url: str) -> str:
    return urlparse(url).hostname or url


def _is_youtube_video(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname not in YOUTUBE_HOSTS:
        return False
    if hostname == "youtu.be":
        return bool(parsed.path.strip("/"))
    return parsed.path == "/watch" or parsed.path.startswith(("/shorts/", "/embed/"))


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _youtube_metadata(url: str) -> ExtractionResult | None:
    """Use YouTube's public oEmbed metadata when the watch page blocks servers."""
    if not _is_youtube_video(url):
        return None
    try:
        response = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    title = str(payload.get("title") or "YouTube video").strip()[:500]
    author = str(payload.get("author_name") or "").strip()
    author_url = str(payload.get("author_url") or "").strip()
    lines = ["## 视频信息", ""]
    if author:
        author_text = _escape_markdown_text(author)
        lines.append(
            f"- 频道：[{author_text}]({author_url})" if author_url else f"- 频道：{author_text}"
        )
    lines.append(f"- 来源：[在 YouTube 观看]({url})")
    lines.extend(["", "> YouTube 页面限制了服务器直接读取，因此这里保存视频元数据和原始链接。"])
    return ExtractionResult(title=title, markdown_content="\n".join(lines))


def extract_page(url: str) -> ExtractionResult:
    normalized_url = url.strip()
    if _is_youtube_video(normalized_url):
        normalized_url = validate_url(normalized_url)
        youtube_result = _youtube_metadata(normalized_url)
        if youtube_result is not None:
            return youtube_result
    try:
        html, final_url = _download_html(normalized_url)
    except FetchError as exc:
        return ExtractionResult(
            title=_fallback_title(normalized_url),
            markdown_content="",
            status="fetch_failed",
            error_message=str(exc),
        )

    metadata = trafilatura.extract_metadata(html)
    title = unescape(metadata.title).strip() if metadata and metadata.title else ""
    markdown = trafilatura.extract(
        html,
        url=final_url,
        output_format="markdown",
        include_links=True,
        include_images=False,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        markdown = trafilatura.extract(
            html,
            url=final_url,
            output_format="markdown",
            include_links=True,
            include_images=False,
            include_tables=True,
            favor_recall=True,
        )
    if not markdown or not markdown.strip():
        description = (
            unescape(metadata.description).strip()
            if metadata and metadata.description
            else ""
        )
        if description:
            return ExtractionResult(
                title=title or _fallback_title(final_url),
                markdown_content=f"## 页面简介\n\n{description}",
            )
        return ExtractionResult(
            title=title or _fallback_title(final_url),
            markdown_content="",
            status="extract_failed",
            error_message="网页可以访问，但没有提取到正文。",
        )
    return ExtractionResult(
        title=title or _fallback_title(final_url),
        markdown_content=markdown.strip(),
    )
