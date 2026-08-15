"""Manual browser acceptance test, run through webapp-testing/with_server.py."""

from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8765"
SCREENSHOT = Path("/tmp/url-bookmark-home.png")
TAG_MENU_SCREENSHOT = Path("/tmp/url-bookmark-tags-open.png")
TRASH_SCREENSHOT = Path("/tmp/url-bookmark-trash.png")
DUPLICATE_SCREENSHOT = Path("/tmp/url-bookmark-duplicate.png")
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
    page.get_by_role("button", name="抓取").click()
    page.wait_for_load_state("networkidle")
    assert "不能访问本机或内网地址" in page.locator(".notice.error").inner_text()

    # A valid URL is retained even if its content cannot be fetched.
    page.locator("#url").fill(TEST_URL)
    page.get_by_role("button", name="抓取").click()
    page.wait_for_load_state("networkidle")
    assert "仍可添加标签并收藏" in page.locator(".notice.success").inner_text()
    assert page.get_by_role("button", name="收藏").is_visible()
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
    page.get_by_label("备注 可选").fill("浏览器验收备注")
    page.get_by_role("button", name="收藏").click()
    page.wait_for_load_state("networkidle")
    assert "收藏成功" in page.locator(".notice.success").inner_text()
    test_card = page.locator(".bookmark-card").filter(
        has=page.locator(f'a[href="{TEST_URL}"]')
    )
    assert test_card.count() == 1
    assert test_card.get_by_role("link", name="Browser Test", exact=True).is_visible()

    # The default grid can be changed to a compact list without reloading.
    assert not page.locator("[data-library]").evaluate("node => node.classList.contains('list-view')")
    page.get_by_role("button", name="列表").click()
    assert page.locator("[data-library]").evaluate("node => node.classList.contains('list-view')")
    page.get_by_role("button", name="卡片").click()
    assert not page.locator("[data-library]").evaluate("node => node.classList.contains('list-view')")

    # Re-entering the same URL does not fetch or create another bookmark.
    page.locator("#url").fill(f"{TEST_URL}#already-saved")
    page.get_by_role("button", name="抓取").click()
    page.wait_for_load_state("networkidle")
    assert "该网址已收藏过，可以修改标签" in page.locator(".notice.success").inner_text()
    assert page.get_by_role("button", name="保存标签").is_visible()
    page.locator("#capture [data-tag-trigger]").click()
    assert page.get_by_role("checkbox", name="Browser Test").is_checked()
    page.screenshot(path=str(DUPLICATE_SCREENSHOT), full_page=True)
    page.locator("#capture .tag-menu-option").filter(has_text="学习").click()
    page.locator("#capture").get_by_role("button", name="完成").click()
    page.get_by_role("button", name="保存标签").click()
    page.wait_for_load_state("networkidle")
    assert "标签已更新" in page.locator(".notice.success").inner_text()
    assert page.locator(f'a[href="{TEST_URL}"]').count() == 1

    # Search filters while typing without a separate submit click.
    search = page.get_by_role("textbox", name="搜索收藏")
    search.fill("does-not-match")
    page.wait_for_timeout(350)
    assert page.locator(".bookmark-card").count() == 0
    search.fill("example.invalid")
    page.wait_for_timeout(350)
    test_card = page.locator(".bookmark-card").filter(
        has=page.locator(f'a[href="{TEST_URL}"]')
    )
    assert test_card.count() == 1

    # Clicking a non-interactive part of the card opens its detail page.
    test_card.locator(".excerpt").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("button", name="重新抓取").is_visible()
    edit_link = page.get_by_role("link", name="编辑")
    assert edit_link.is_visible()
    assert edit_link.evaluate("node => getComputedStyle(node).alignItems") == "center"
    action_tops = page.locator(".detail-actions > *").evaluate_all(
        "nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))"
    )
    assert len(set(action_tops)) == 1
    assert page.locator('#notes textarea').input_value() == "浏览器验收备注"

    page.locator('#notes textarea').fill("更新后的备注")
    page.locator("#notes").get_by_role("button", name="保存修改").click()
    page.wait_for_load_state("networkidle")
    assert page.locator('#notes textarea').input_value() == "更新后的备注"
    page.locator("#notes").get_by_role("button", name="删除备注").click()
    page.wait_for_load_state("networkidle")
    assert page.locator('#notes textarea').input_value() == ""

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

    page.get_by_role("link", name="返回收藏").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("combobox", name="按标签筛选").select_option(label="工作")
    page.wait_for_timeout(250)
    test_card = page.locator(".bookmark-card").filter(
        has=page.locator(f'a[href="{TEST_URL}"]')
    )
    assert test_card.count() == 1
    test_card.get_by_role("button", name="删除").click()
    confirm_dialog = page.locator("dialog[open]")
    assert confirm_dialog.get_by_text("确定删除这条收藏吗？", exact=True).is_visible()
    confirm_dialog.get_by_role("button", name="取消").click()
    assert test_card.count() == 1

    test_card.get_by_role("button", name="删除").click()
    page.locator("dialog[open]").get_by_role("button", name="确认移入回收站").click()
    page.wait_for_load_state("networkidle")
    assert page.locator(f'a[href="{TEST_URL}"]').count() == 0

    page.get_by_role("link", name="回收站").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="回收站").is_visible()
    back_to_library = page.get_by_role("link", name="返回我的收藏")
    assert back_to_library.evaluate("node => getComputedStyle(node).alignItems") == "center"
    trash_card = page.locator(".trash-card").filter(has_text="Browser acceptance bookmark")
    assert trash_card.count() == 1
    page.screenshot(path=str(TRASH_SCREENSHOT), full_page=True)
    trash_card.get_by_role("button", name="撤销删除").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_text("Browser acceptance bookmark", exact=True).count() == 0

    back_to_library.click()
    page.wait_for_load_state("networkidle")
    test_card = page.locator(".bookmark-card").filter(
        has=page.locator(f'a[href="{TEST_URL}"]')
    )
    assert test_card.count() == 1
    test_card.get_by_role("button", name="删除").click()
    page.locator("dialog[open]").get_by_role("button", name="确认移入回收站").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="回收站").click()
    page.wait_for_load_state("networkidle")
    trash_card = page.locator(".trash-card").filter(has_text="Browser acceptance bookmark")
    trash_card.get_by_role("button", name="彻底删除").click()
    page.locator("dialog[open]").get_by_role("button", name="确认彻底删除").click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_text("Browser acceptance bookmark", exact=True).count() == 0

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    assert not browser_errors, browser_errors
    print(
        "Browser smoke test passed; screenshots: "
        f"{SCREENSHOT}, {TAG_MENU_SCREENSHOT}, {TRASH_SCREENSHOT}, "
        f"{DUPLICATE_SCREENSHOT}"
    )
    browser.close()
