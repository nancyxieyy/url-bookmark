"""Load the unpacked extension and exercise browser-local DOM capture."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import Route, sync_playwright


EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
SCREENSHOT = Path("/tmp/url-bookmark-browser-capture.png")
recent = [
    {
        "id": 7,
        "url": "https://example.com/old",
        "title": "Earlier bookmark",
        "tags": ["Inbox"],
        "status": "success",
        "error_message": None,
        "notes": "",
        "duplicate": False,
        "capture_method": "server",
    }
]
created_payload = {}
suggestion_requests = 0
ai_should_fail = False


ARTICLE_HTML = """<!doctype html>
<html>
<head>
  <title>Current rendered article</title>
</head>
<body>
  <form><label>Password <input type="password" value="NEVER_UPLOAD_THIS"></label></form>
  <nav>Navigation that should not become the article body.</nav>
  <article>
    <h1>Browser rendered article</h1>
    <p>This content was rendered inside the browser after the page loaded. It is deliberately long enough for Mozilla Readability to recognize it as the primary article content.</p>
    <p>The saved Markdown should preserve useful links and images while excluding forms, password fields, scripts, and other private browser state from the capture.</p>
    <p><a href="/docs">Read the related documentation</a></p>
    <img src="/images/example.png" alt="Example image">
  </article>
</body>
</html>"""

PLATFORM_PAGES = {
    "https://www.xiaohongshu.com/explore/test-note": """<!doctype html><html><head>
      <title>小红书测试笔记</title>
      <meta property="og:title" content="小红书测试笔记">
      <meta property="og:image" content="https://www.xiaohongshu.com/note-cover.jpg">
    </head><body><main id="noteContainer"><section class="note-content">
      <h1 class="title">小红书测试笔记</h1><p class="desc">这是应当被保存的小红书笔记正文，而不是网站页脚。</p>
      <div class="author-wrapper"><span class="username">测试作者</span></div>
      <div class="swiper-slide"><img src="/note-image.jpg"></div>
    </section></main><footer>不应成为正文的网站页脚</footer></body></html>""",
    "https://www.youtube.com/watch?v=test-video": """<!doctype html><html><head>
      <title>YouTube 测试视频</title>
      <meta property="og:title" content="YouTube 测试视频">
      <meta property="og:description" content="这是视频简介，包含创作者希望保存的文字信息。">
      <meta property="og:image" content="https://www.youtube.com/video-cover.jpg">
    </head><body><main><div id="owner"><span id="channel-name">测试频道</span></div>
      <div id="description-inline-expander"><div id="description">这是视频简介，包含创作者希望保存的文字信息。</div></div>
    </main></body></html>""",
    "https://www.reddit.com/r/python/comments/test/post": """<!doctype html><html><head>
      <title>Reddit test post</title><meta property="og:image" content="https://www.reddit.com/post-image.jpg">
    </head><body><shreddit-post post-title="Reddit test post" author="example_user" subreddit-name="python">
      <div slot="text-body"><p>This is the Reddit post body that should be preserved with its useful content.</p></div>
      <div slot="post-media-container"><img src="/post-image.jpg"></div>
    </shreddit-post></body></html>""",
}


def route_platform_pages(route: Route) -> None:
    if route.request.url in PLATFORM_PAGES:
        route.fulfill(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=PLATFORM_PAGES[route.request.url],
        )
    elif route.request.url.endswith(".jpg"):
        route.fulfill(status=200, content_type="image/jpeg", body=b"")
    else:
        route.abort()


def route_requests(route: Route) -> None:
    global recent, created_payload, suggestion_requests, ai_should_fail
    url = route.request.url
    if url == "https://url-bookmark.onrender.com/current":
        route.fulfill(status=200, content_type="text/html", body=ARTICLE_HTML)
        return
    if url == "https://url-bookmark.onrender.com/images/example.png":
        route.fulfill(status=200, content_type="image/png", body=b"")
        return
    if url == "https://url-bookmark.onrender.com/empty":
        route.fulfill(
            status=200,
            content_type="text/html",
            body="<title>URL only page</title><div>Short page without article content.</div>",
        )
        return
    if url == "https://url-bookmark.onrender.com/ai-failure":
        route.fulfill(
            status=200,
            content_type="text/html",
            body=(
                "<title>JS rendered article</title><main id='app'></main>"
                "<script>document.querySelector('#app').innerHTML = `"
                "<article><h1>JS rendered article</h1>"
                "<p>This article was inserted by JavaScript after the initial HTML loaded, and it contains enough meaningful text for Readability to identify the rendered body correctly.</p>"
                "<p>The AI request will fail during this scenario, but saving the browser Markdown must remain available to the user without interruption.</p>"
                "</article>`;</script>"
            ),
        )
        return
    if route.request.headers.get("authorization") != "Bearer test-extension-token":
        route.fulfill(
            status=401,
            content_type="application/json",
            body='{"detail":"Extension API Token 无效或未配置。"}',
        )
        return
    if url.endswith("/api/tags"):
        payload = ["Inbox", "Python"]
    elif "/api/bookmarks/recent" in url:
        payload = recent[:3]
    elif url.endswith("/api/bookmarks/check-duplicate"):
        payload = {"duplicate": False, "bookmark": None}
    elif url.endswith("/api/bookmarks/browser-tag-suggestions"):
        suggestion_requests += 1
        if ai_should_fail:
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"AI 标签推荐暂时不可用"}',
            )
            return
        payload = {"existing_tags": ["Python"], "new_tags": ["Readability"]}
    elif url.endswith("/api/bookmarks"):
        created_payload = route.request.post_data_json
        payload = {
            "id": 8,
            "url": created_payload["url"],
            "title": created_payload["title"],
            "tags": created_payload["tags"],
            "status": "success" if created_payload["markdown_content"] else "extract_failed",
            "error_message": None if created_payload["markdown_content"] else "未保存正文，仅保存网址。",
            "notes": created_payload["notes"],
            "duplicate": False,
            "capture_method": "browser",
        }
        recent = [payload, *recent]
    elif url.endswith("/api/bookmarks/7/delete"):
        recent = [item for item in recent if item["id"] != 7]
        payload = {"ok": True}
    else:
        route.abort()
        return
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


with TemporaryDirectory(prefix="url-bookmark-extension-") as profile_dir:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile_dir,
            channel="chromium",
            headless=True,
            args=[
                f"--disable-extensions-except={EXTENSION_DIR}",
                f"--load-extension={EXTENSION_DIR}",
            ],
        )
        context.route("https://url-bookmark.onrender.com/**", route_requests)
        context.route("https://www.xiaohongshu.com/**", route_platform_pages)
        context.route("https://www.youtube.com/**", route_platform_pages)
        context.route("https://www.reddit.com/**", route_platform_pages)
        console_errors: list[str] = []
        context.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
        extension_id = worker.url.split("/")[2]
        browser_errors: list[str] = []

        options_page = context.new_page()
        options_page.goto(f"chrome-extension://{extension_id}/options.html")
        options_page.locator("#server-url").fill("https://url-bookmark.onrender.com/")
        options_page.locator("#api-token").fill("test-extension-token")
        options_page.get_by_role("button", name="保存设置").click()
        options_page.get_by_text("设置已保存。").wait_for()
        options_page.close()

        platform_expectations = {
            "https://www.xiaohongshu.com/explore/test-note": (
                "✓ 已读取小红书笔记", "小红书测试笔记", "笔记图片"
            ),
            "https://www.youtube.com/watch?v=test-video": (
                "✓ 已读取 YouTube 视频信息", "测试频道", "视频封面"
            ),
            "https://www.reddit.com/r/python/comments/test/post": (
                "✓ 已读取 Reddit 帖子", "example\\_user", "This is the Reddit post body"
            ),
        }
        for platform_url, expected in platform_expectations.items():
            platform_page = context.new_page()
            platform_page.goto(platform_url)
            platform_page.wait_for_load_state("networkidle")
            platform_page.add_script_tag(path=EXTENSION_DIR / "vendor" / "Readability.js")
            platform_page.add_script_tag(path=EXTENSION_DIR / "vendor" / "turndown.js")
            platform_page.add_script_tag(path=EXTENSION_DIR / "capture.js")
            captured = platform_page.evaluate("captureBookmarkPage()")
            assert captured["readability"]["label"] == expected[0]
            markdown = captured["readability"]["markdownContent"]
            assert expected[1] in markdown, (platform_url, markdown)
            assert expected[2] in markdown, (platform_url, markdown)
            platform_page.close()

        article_page = context.new_page()
        article_page.goto("https://url-bookmark.onrender.com/current")
        article_page.wait_for_load_state("networkidle")
        article_tab_id = worker.evaluate(
            "async () => (await chrome.tabs.query({url: 'https://url-bookmark.onrender.com/current'}))[0].id"
        )

        popup = context.new_page()
        popup.add_init_script(
            f"""
            chrome.tabs.query = async () => [{{
              id: {article_tab_id},
              title: 'Current rendered article',
              url: 'https://url-bookmark.onrender.com/current'
            }}];
            """
        )
        popup.on("pageerror", lambda error: browser_errors.append(str(error)))
        popup.goto(f"chrome-extension://{extension_id}/popup.html")
        popup.get_by_text("已从浏览器读取正文", exact=False).wait_for()

        assert popup.locator("#bookmark-form").is_visible()
        assert popup.get_by_text("推荐标签会自动显示在标签菜单中。").is_visible()
        assert created_payload == {}

        popup.get_by_role("button", name="选择标签").click()
        popup.get_by_role("button", name="＋ Readability").wait_for()
        assert suggestion_requests == 1
        popup.get_by_role("button", name="＋ Readability").click()
        popup.get_by_placeholder("添加新的标签").fill("阅读")
        popup.get_by_placeholder("添加新的标签").press("Enter")
        popup.get_by_role("button", name="完成").click()
        popup.get_by_label("备注 可选").fill("浏览器正文采集测试")
        popup.get_by_role("button", name="收藏 →").click()
        popup.get_by_text("已收藏：Current rendered article").wait_for()

        assert created_payload["capture_method"] == "browser"
        assert "rendered inside the browser" in created_payload["markdown_content"]
        assert "NEVER_UPLOAD_THIS" not in created_payload["markdown_content"]
        assert "url-bookmark.onrender.com/images/example.png" in created_payload["markdown_content"]
        assert set(created_payload["tags"]) == {"Readability", "阅读"}
        assert not browser_errors, browser_errors
        popup.screenshot(path=str(SCREENSHOT), full_page=True)

        empty_page = context.new_page()
        empty_page.goto("https://url-bookmark.onrender.com/empty")
        empty_tab_id = worker.evaluate(
            "async () => (await chrome.tabs.query({url: 'https://url-bookmark.onrender.com/empty'}))[0].id"
        )
        empty_popup = context.new_page()
        empty_popup.on("pageerror", lambda error: browser_errors.append(str(error)))
        empty_popup.add_init_script(
            f"""
            chrome.tabs.query = async () => [{{
              id: {empty_tab_id},
              title: 'URL only page',
              url: 'https://url-bookmark.onrender.com/empty'
            }}];
            """
        )
        empty_popup.goto(f"chrome-extension://{extension_id}/popup.html")
        empty_popup.get_by_text("未识别到正文，仍可只收藏网址。").wait_for()
        empty_popup.get_by_role("button", name="只收藏网址").click()
        empty_popup.get_by_role("button", name="收藏 →").click()
        empty_popup.get_by_text("已收藏：URL only page").wait_for()
        assert created_payload["markdown_content"] == ""
        assert created_payload["capture_method"] == "browser"
        empty_popup.close()
        empty_page.close()

        ai_should_fail = True
        js_page = context.new_page()
        js_page.goto("https://url-bookmark.onrender.com/ai-failure")
        js_page.wait_for_load_state("networkidle")
        js_tab_id = worker.evaluate(
            "async () => (await chrome.tabs.query({url: 'https://url-bookmark.onrender.com/ai-failure'}))[0].id"
        )
        js_popup = context.new_page()
        js_popup.on("pageerror", lambda error: browser_errors.append(str(error)))
        js_popup.add_init_script(
            f"""
            chrome.tabs.query = async () => [{{
              id: {js_tab_id},
              title: 'JS rendered article',
              url: 'https://url-bookmark.onrender.com/ai-failure'
            }}];
            """
        )
        js_popup.goto(f"chrome-extension://{extension_id}/popup.html")
        js_popup.get_by_text("已从浏览器读取正文", exact=False).wait_for()
        js_popup.wait_for_timeout(300)
        assert suggestion_requests == 2
        js_popup.get_by_role("button", name="收藏 →").click()
        js_popup.get_by_text("已收藏：JS rendered article").wait_for()
        assert "inserted by JavaScript" in created_payload["markdown_content"]
        assert not browser_errors, browser_errors
        unexpected_console_errors = [
            message for message in console_errors if "503 (Service Unavailable)" not in message
        ]
        assert not unexpected_console_errors, unexpected_console_errors
        js_popup.close()
        js_page.close()

        popup.evaluate("async () => await chrome.storage.local.set({apiToken: 'invalid-token'})")
        popup.reload()
        popup.get_by_text("API Token 无效，请在扩展设置中重新配置。").wait_for()
        print(
            "Browser capture smoke test passed; "
            f"id={extension_id}; screenshot={SCREENSHOT}"
        )
        context.close()
