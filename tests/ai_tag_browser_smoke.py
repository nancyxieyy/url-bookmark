import sys
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Route, sync_playwright
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.models import Bookmark, Tag


BASE_URL = "http://127.0.0.1:8765"
SCREENSHOT = Path("/tmp/url-bookmark-ai-tags.png")
DETAIL_SCREENSHOT = Path("/tmp/url-bookmark-markdown-detail.png")
test_title = f"AI tag browser test {uuid4().hex}"


with Session(engine) as session:
    preexisting_tag_ids = set(session.exec(select(Tag.id)).all())
    bookmark = Bookmark(
        url="https://example.com/fastapi-guide",
        title=test_title,
        markdown_content="# FastAPI\n\nBuild Python backend APIs with FastAPI.",
        status="success",
        is_draft=True,
    )
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)
    bookmark_id = bookmark.id


def fulfill_suggestions(route: Route):
    route.fulfill(
        status=200,
        content_type="application/json",
        body='{"existing_tags":["技术"],"new_tags":["FastAPI"]}',
    )


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        browser_errors: list[str] = []
        page.on("console", lambda message: browser_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.route("**/api/bookmarks/*/tag-suggestions", fulfill_suggestions)

        page.goto(f"{BASE_URL}/?suggest_for={bookmark_id}#capture")
        page.wait_for_load_state("networkidle")
        assert page.url.startswith(f"{BASE_URL}/?suggest_for={bookmark_id}")
        assert page.get_by_text("正文已抓取，可以确认标签并收藏", exact=False).is_visible()
        capture = page.locator("#capture")
        capture.locator("[data-tag-trigger]").click()
        assert page.get_by_text("优先匹配已有标签", exact=True).is_visible()
        assert page.get_by_text("建议的新标签", exact=True).is_visible()
        assert page.get_by_role("button", name="＋ 技术").is_visible()
        assert page.get_by_role("button", name="＋ FastAPI").is_visible()

        page.get_by_role("button", name="＋ 技术").click()
        page.get_by_role("button", name="＋ FastAPI").click()
        assert page.get_by_role("button", name="✓ 技术").get_attribute("aria-pressed") == "true"
        assert page.get_by_role("button", name="✓ FastAPI").get_attribute("aria-pressed") == "true"

        assert capture.get_by_role("checkbox", name="技术").is_checked()
        assert capture.get_by_role("checkbox", name="FastAPI").is_checked()
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        capture.get_by_role("button", name="完成").click()

        page.get_by_role("button", name="收藏").click()
        page.wait_for_load_state("networkidle")
        assert "suggest_for=" not in page.url
        saved_card = page.locator(".bookmark-card").filter(has_text=test_title)
        assert saved_card.get_by_text("FastAPI", exact=True).is_visible()
        assert saved_card.get_by_text("技术", exact=True).is_visible()
        saved_card.locator(".excerpt").click()
        page.wait_for_load_state("networkidle")
        assert page.locator(".markdown-body h1").get_by_text("FastAPI", exact=True).is_visible()
        assert page.locator(".markdown-panel pre").count() == 0
        page.screenshot(path=str(DETAIL_SCREENSHOT), full_page=True)
        assert not browser_errors, browser_errors
        browser.close()
finally:
    with Session(engine) as session:
        saved = session.get(Bookmark, bookmark_id)
        if saved is not None:
            session.delete(saved)
            session.commit()
        for tag in session.exec(select(Tag)).all():
            if tag.id not in preexisting_tag_ids and not tag.bookmarks:
                session.delete(tag)
        session.commit()


print(
    "AI tag browser smoke test passed; screenshots: "
    f"{SCREENSHOT}, {DETAIL_SCREENSHOT}"
)
