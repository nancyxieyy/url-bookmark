"""Load the unpacked extension and exercise its two-stage capture UI."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import Route, sync_playwright


EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
SCREENSHOT = Path("/tmp/url-bookmark-extension.png")
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
    }
]


def api_response(route: Route) -> None:
    global recent
    url = route.request.url
    if url.endswith("/api/tags"):
        payload = ["Inbox", "Python"]
    elif "/api/bookmarks/recent" in url:
        payload = recent[:3]
    elif url.endswith("/api/bookmarks/preview"):
        payload = {
            "id": 8,
            "url": "https://example.com/current",
            "title": "Current article",
            "tags": [],
            "status": "success",
            "error_message": None,
            "notes": "",
            "duplicate": False,
        }
    elif url.endswith("/api/bookmarks/8/tag-suggestions"):
        payload = {"existing_tags": ["Python"], "new_tags": ["FastAPI"]}
    elif url.endswith("/api/bookmarks/8/confirm"):
        request = route.request.post_data_json
        payload = {
            "id": 8,
            "url": "https://example.com/current",
            "title": "Current article",
            "tags": request["tags"],
            "status": "success",
            "error_message": None,
            "notes": request["notes"],
            "duplicate": False,
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
        worker = (
            context.service_workers[0]
            if context.service_workers
            else context.wait_for_event("serviceworker")
        )
        extension_id = worker.url.split("/")[2]
        browser_errors: list[str] = []

        page = context.new_page()
        page.add_init_script(
            """
            chrome.tabs.query = async () => [{
              title: 'Current article',
              url: 'https://example.com/current'
            }];
            """
        )
        page.route("https://url-bookmark.onrender.com/api/**", api_response)
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.goto(f"chrome-extension://{extension_id}/popup.html")

        assert page.get_by_role("heading", name="URL Bookmark").is_visible()
        assert page.get_by_role("button", name="抓取当前页面 →").is_visible()
        assert page.get_by_text("Earlier bookmark", exact=True).is_visible()

        page.get_by_role("button", name="抓取当前页面 →").click()
        page.get_by_text("AI 推荐", exact=False).wait_for()
        assert page.locator("#preview-button").is_hidden()
        assert page.locator("#bookmark-form").is_visible()
        page.get_by_role("button", name="＋ FastAPI").click()
        page.get_by_label("备注 可选").fill("插件里的备注")
        page.get_by_role("button", name="收藏 →").click()
        page.get_by_text("已收藏：Current article").wait_for()
        assert page.locator(".recent-item").filter(has_text="Current article").is_visible()

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator(".recent-item").filter(has_text="Earlier bookmark").get_by_role(
            "button", name="删除"
        ).click()
        page.get_by_text("已移入回收站。").wait_for()
        assert page.get_by_text("Earlier bookmark", exact=True).count() == 0
        assert not browser_errors, browser_errors

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        print(
            f"Extension smoke test passed; id={extension_id}; screenshot={SCREENSHOT}"
        )
        context.close()
