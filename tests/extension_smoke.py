"""Load the unpacked extension in Chromium and verify its popup runtime."""

from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright


EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
SCREENSHOT = Path("/tmp/url-bookmark-extension.png")


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
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.goto(f"chrome-extension://{extension_id}/popup.html")
        page.wait_for_load_state("networkidle")

        assert page.get_by_role("heading", name="URL Bookmark").is_visible()
        assert page.get_by_role("button", name="保存当前网页 →").is_visible()
        assert "无法连接本地服务" not in page.locator("body").inner_text()
        assert not browser_errors, browser_errors

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        print(
            f"Extension smoke test passed; id={extension_id}; screenshot={SCREENSHOT}"
        )
        context.close()
