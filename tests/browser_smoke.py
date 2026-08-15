"""Manual browser acceptance test, run through webapp-testing/with_server.py."""

from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8765"
SCREENSHOT = Path("/tmp/url-bookmark-home.png")
TAG_MENU_SCREENSHOT = Path("/tmp/url-bookmark-tags-open.png")
TEST_URL = f"https://example.invalid/article?browser-test={uuid4().hex}"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    browser_errors: list[str] = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="收藏一个网址， 留下它真正重要的内容。").is_visible()
    assert page.locator(".capture-form").is_visible()

    # Security validation happens before a bookmark is created.
    page.locator("#url").fill("http://127.0.0.1/private")
    page.get_by_role("button", name="收藏并抓取").click()
    page.wait_for_load_state("networkidle")
    assert "不能访问本机或内网地址" in page.locator(".notice.error").inner_text()

    # A valid URL is retained even if its content cannot be fetched.
    page.locator("#url").fill(TEST_URL)
    page.locator("[data-tag-trigger]").click()
    assert page.locator("[data-tag-menu]").is_visible()
    assert page.get_by_placeholder("添加新的标签").is_visible()
    page.get_by_placeholder("添加新的标签").fill("Browser Test")
    page.get_by_placeholder("添加新的标签").press("Enter")
    page.locator(".tag-menu-option").filter(has_text="AI").click()
    page.locator(".tag-menu-option").filter(has_text="稍后读").click()
    assert page.get_by_role("checkbox", name="Browser Test").is_checked()
    assert page.get_by_role("checkbox", name="AI").is_checked()
    assert page.get_by_role("checkbox", name="稍后读").is_checked()
    page.screenshot(path=str(TAG_MENU_SCREENSHOT), full_page=True)
    page.get_by_role("button", name="完成").click()
    assert page.locator("[data-tag-menu]").is_hidden()
    page.get_by_role("button", name="收藏并抓取").click()
    page.wait_for_load_state("networkidle")
    assert "网址已收藏" in page.locator(".notice.success").inner_text()
    test_card = page.locator(".bookmark-card").filter(
        has=page.locator(f'a[href="{TEST_URL}"]')
    )
    assert test_card.count() == 1
    assert test_card.get_by_role("link", name="Browser Test", exact=True).is_visible()

    test_card.get_by_role("link", name="查看详情 →").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("button", name="重新抓取").is_visible()
    assert page.get_by_role("link", name="编辑").is_visible()

    page.get_by_role("link", name="编辑").click()
    page.locator("#title").fill("Browser acceptance bookmark")
    page.locator("[data-tag-trigger]").click()
    assert page.get_by_role("checkbox", name="Browser Test").is_checked()
    assert page.get_by_role("checkbox", name="AI").is_checked()
    page.locator(".tag-menu-option").filter(has_text="AI").click()
    page.locator(".tag-menu-option").filter(has_text="工作").click()
    assert not page.get_by_role("checkbox", name="AI").is_checked()
    assert page.get_by_role("checkbox", name="工作").is_checked()
    page.get_by_role("button", name="完成").click()
    page.get_by_role("button", name="保存修改").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="Browser acceptance bookmark").is_visible()
    assert page.get_by_text("工作", exact=True).is_visible()
    assert page.get_by_text("AI", exact=True).count() == 0

    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="删除").click()
    page.wait_for_load_state("networkidle")
    assert page.locator(f'a[href="{TEST_URL}"]').count() == 0

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    assert not browser_errors, browser_errors
    print(
        "Browser smoke test passed; screenshots: "
        f"{SCREENSHOT}, {TAG_MENU_SCREENSHOT}"
    )
    browser.close()
