from collections.abc import Generator
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

import app.database as database_module
from app.database import get_database_url, get_session
from app.database import normalize_database_url
from app.main import app, url_identity
from app.models import Bookmark
from app.schemas import ExtractionResult
from app.services.tag_recommender import TagSuggestions


def test_normalize_database_url_for_supabase():
    assert normalize_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert normalize_database_url("sqlite:///data/test.db") == "sqlite:///data/test.db"


def test_url_identity_ignores_fragment_host_case_and_default_port():
    assert url_identity("https://EXAMPLE.com:443/article#section") == (
        url_identity("https://example.com/article")
    )
    assert url_identity("https://example.com") == url_identity("https://example.com/")
    assert url_identity("https://example.com/article?a=1") != url_identity(
        "https://example.com/article?a=2"
    )


def test_build_supabase_url_from_separate_password(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_PASSWORD", "p@ss:/word")
    monkeypatch.setenv("SUPABASE_DB_HOST", "pooler.example.com")
    monkeypatch.setenv("SUPABASE_DB_USER", "postgres.project-ref")

    url = get_database_url()

    assert url.username == "postgres.project-ref"
    assert url.password == "p@ss:/word"
    assert url.host == "pooler.example.com"
    assert url.database == "postgres"
    assert url.query["sslmode"] == "require"


def test_startup_migrates_existing_bookmark_table(tmp_path, monkeypatch):
    old_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE bookmark ("
                "id INTEGER PRIMARY KEY, url VARCHAR NOT NULL, title VARCHAR NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bookmark (id, url, title) VALUES "
                "(1, 'https://www.zhihu.com/question/1', 'Old Zhihu item')"
            )
        )

    monkeypatch.setattr(database_module, "engine", old_engine)
    database_module.create_db_and_tables()

    columns = {item["name"] for item in inspect(old_engine).get_columns("bookmark")}
    assert "deleted_at" in columns
    assert "is_draft" in columns
    assert "notes" in columns
    assert "platform" in columns
    with old_engine.connect() as connection:
        assert connection.execute(
            text("SELECT platform FROM bookmark WHERE id = 1")
        ).scalar_one() == "知乎"


def test_create_search_edit_and_delete_bookmark(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(
        "app.main.validate_url", lambda url: url.strip()
    )
    monkeypatch.setattr(
        "app.main.extract_page",
        lambda url: ExtractionResult("Test article", "# Body\n\nSearchable text"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    try:
        with TestClient(app) as client:
            response = client.post(
                "/bookmarks/preview",
                data={"url": "https://example.com/article"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert "/?suggest_for=" in response.headers["location"]
            assert "#capture" in response.headers["location"]

            search = client.get("/?q=Searchable&tag=AI")
            assert search.status_code == 200
            assert "Test article" not in search.text

            with Session(engine) as session:
                bookmark = session.exec(select(Bookmark)).one()
                bookmark_id = bookmark.id
                assert bookmark.is_draft is True

            confirmation = client.get(f"/?suggest_for={bookmark_id}")
            assert confirmation.status_code == 200
            assert "正文已抓取，可以确认标签并收藏" in confirmation.text
            assert "AI 推荐" in confirmation.text
            assert ">收藏 <" in confirmation.text
            assert "回收站" in confirmation.text

            saved_tags = client.post(
                f"/bookmarks/{bookmark_id}/tags",
                data={"tag_choices": ["AI"], "notes": "第一次阅读时的备注"},
                follow_redirects=False,
            )
            assert saved_tags.status_code == 303
            assert saved_tags.headers["location"].endswith("#library")

            with Session(engine) as session:
                assert session.get(Bookmark, bookmark_id).is_draft is False
                assert session.get(Bookmark, bookmark_id).notes == "第一次阅读时的备注"
            search = client.get("/?q=Searchable&tag=AI")
            assert "Test article" in search.text

            def unexpected_extract(_: str):
                raise AssertionError("duplicate URL must not be fetched again")

            monkeypatch.setattr("app.main.extract_page", unexpected_extract)
            duplicate = client.post(
                "/bookmarks/preview",
                data={"url": "https://EXAMPLE.com:443/article#section"},
                follow_redirects=False,
            )
            assert duplicate.status_code == 303
            assert f"duplicate_for={bookmark_id}" in duplicate.headers["location"]
            duplicate_page = client.get(f"/?duplicate_for={bookmark_id}")
            assert "该网址已收藏过，可以修改标签" in duplicate_page.text
            assert "保存标签" in duplicate_page.text
            with Session(engine) as session:
                assert len(session.exec(select(Bookmark)).all()) == 1

            updated_duplicate_tags = client.post(
                f"/bookmarks/{bookmark_id}/tags?duplicate=1",
                data={"tag_choices": ["AI", "Python"]},
                follow_redirects=False,
            )
            assert "标签已更新" in unquote(
                updated_duplicate_tags.headers["location"]
            )
            monkeypatch.setattr(
                "app.main.extract_page",
                lambda url: ExtractionResult("Test article", "# Body\n\nSearchable text"),
            )

            monkeypatch.setattr(
                "app.main.recommend_tags",
                lambda title, markdown, existing: TagSuggestions(
                    existing_tags=["AI", "工作"],
                    new_tags=["FastAPI"],
                ),
            )
            suggestions = client.post(
                f"/api/bookmarks/{bookmark_id}/tag-suggestions"
            )
            assert suggestions.status_code == 200
            assert suggestions.json() == {
                "existing_tags": ["工作"],
                "new_tags": ["FastAPI"],
            }

            edit = client.post(
                f"/bookmarks/{bookmark_id}/edit",
                data={
                    "title": "Edited title",
                    "url": "https://example.com/edited",
                    "tag_choices": ["工作"],
                },
                follow_redirects=False,
            )
            assert edit.status_code == 303

            detail = client.get(f"/bookmarks/{bookmark_id}")
            assert "Edited title" in detail.text
            assert "工作" in detail.text
            assert '<h1>Body</h1>' in detail.text
            assert "第一次阅读时的备注" not in detail.text

            saved_note = client.post(
                f"/bookmarks/{bookmark_id}/note",
                data={"notes": "之后再整理", "action": "save"},
                follow_redirects=False,
            )
            assert saved_note.status_code == 303
            assert "之后再整理" in client.get(f"/bookmarks/{bookmark_id}").text
            deleted_note = client.post(
                f"/bookmarks/{bookmark_id}/note",
                data={"action": "delete"},
                follow_redirects=False,
            )
            assert deleted_note.status_code == 303
            with Session(engine) as session:
                assert session.get(Bookmark, bookmark_id).notes == ""

            deleted = client.post(
                f"/bookmarks/{bookmark_id}/delete", follow_redirects=False
            )
            assert deleted.status_code == 303
            with Session(engine) as session:
                trashed = session.get(Bookmark, bookmark_id)
                assert trashed is not None
                assert trashed.deleted_at is not None

            home = client.get("/")
            assert "Edited title" not in home.text
            trash = client.get("/trash")
            assert trash.status_code == 200
            assert "Edited title" in trash.text

            restored = client.post(
                f"/bookmarks/{bookmark_id}/restore", follow_redirects=False
            )
            assert restored.status_code == 303
            with Session(engine) as session:
                assert session.get(Bookmark, bookmark_id).deleted_at is None
            assert "Edited title" in client.get("/").text

            client.post(f"/bookmarks/{bookmark_id}/delete")
            permanent = client.post(
                f"/bookmarks/{bookmark_id}/permanent-delete",
                follow_redirects=False,
            )
            assert permanent.status_code == 303
            with Session(engine) as session:
                assert session.get(Bookmark, bookmark_id) is None

            with Session(engine) as session:
                expired = Bookmark(
                    url="https://example.com/expired",
                    title="Expired trash item",
                    status="fetch_failed",
                    deleted_at=datetime.now(timezone.utc) - timedelta(days=31),
                )
                session.add(expired)
                session.commit()
                session.refresh(expired)
                expired_id = expired.id
            expired_cleanup = client.get("/trash")
            assert "Expired trash item" not in expired_cleanup.text
            with Session(engine) as session:
                assert session.get(Bookmark, expired_id) is None

            with Session(engine) as session:
                stale_draft = Bookmark(
                    url="https://example.com/stale-draft",
                    title="Stale draft",
                    status="success",
                    is_draft=True,
                    updated_at=datetime.now(timezone.utc) - timedelta(hours=25),
                )
                session.add(stale_draft)
                session.commit()
                session.refresh(stale_draft)
                stale_draft_id = stale_draft.id
            assert "Stale draft" not in client.get("/").text
            with Session(engine) as session:
                assert session.get(Bookmark, stale_draft_id) is None

            api_response = client.post(
                "/api/bookmarks",
                json={
                    "url": "https://example.com/from-extension",
                    "title": "Browser tab title",
                    "tags": ["Inbox", "Extension"],
                    "notes": "插件备注",
                },
            )
            assert api_response.status_code == 201
            assert api_response.json()["title"] == "Test article"
            assert api_response.json()["tags"] == ["Inbox", "Extension"]
            assert api_response.json()["duplicate"] is False
            assert api_response.json()["notes"] == "插件备注"

            preview_api = client.post(
                "/api/bookmarks/preview",
                json={
                    "url": "https://example.com/two-step-extension",
                    "title": "Browser preview title",
                    "tags": [],
                    "notes": "",
                },
            )
            assert preview_api.status_code == 201
            preview_id = preview_api.json()["id"]
            confirmed_api = client.post(
                f"/api/bookmarks/{preview_id}/confirm",
                json={"tags": ["Inbox"], "notes": "确认时填写"},
            )
            assert confirmed_api.status_code == 200
            assert confirmed_api.json()["notes"] == "确认时填写"
            assert confirmed_api.json()["tags"] == ["Inbox"]
            recent_api = client.get("/api/bookmarks/recent?limit=3")
            assert recent_api.status_code == 200
            assert any(item["id"] == preview_id for item in recent_api.json())
            deleted_api = client.post(f"/api/bookmarks/{preview_id}/delete")
            assert deleted_api.status_code == 200
            assert all(
                item["id"] != preview_id
                for item in client.get("/api/bookmarks/recent?limit=10").json()
            )

            duplicate_api = client.post(
                "/api/bookmarks",
                json={
                    "url": "https://EXAMPLE.com:443/from-extension#same-page",
                    "title": "Duplicate browser tab",
                    "tags": ["New tag"],
                },
            )
            assert duplicate_api.status_code == 200
            assert duplicate_api.json()["id"] == api_response.json()["id"]
            assert duplicate_api.json()["duplicate"] is True
            assert duplicate_api.json()["tags"] == ["Inbox", "Extension", "New tag"]

            tags_response = client.get("/api/tags")
            assert tags_response.status_code == 200
            assert tags_response.json() == ["Extension", "Inbox", "New tag"]

            cors_response = client.options(
                "/api/bookmarks",
                headers={
                    "Origin": f"chrome-extension://{'a' * 32}",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert cors_response.status_code == 200
            assert cors_response.headers["access-control-allow-origin"].startswith(
                "chrome-extension://"
            )

            youtube_response = client.post(
                "/api/bookmarks",
                json={
                    "url": "https://www.youtube.com/watch?v=platform-test",
                    "title": "YouTube tab",
                    "tags": ["Video"],
                },
            )
            assert youtube_response.status_code == 201
            youtube_id = youtube_response.json()["id"]
            with Session(engine) as session:
                youtube_item = session.get(Bookmark, youtube_id)
                other_item = session.get(Bookmark, api_response.json()["id"])
                assert youtube_item.platform == "YouTube"
                assert other_item.platform == "其他"
                youtube_item.title = "YouTube platform item"
                youtube_item.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
                other_item.title = "Other platform item"
                other_item.updated_at = datetime.now(timezone.utc)
                session.add(youtube_item)
                session.add(other_item)
                session.commit()

            youtube_page = client.get("/?platform=YouTube")
            assert "YouTube platform item" in youtube_page.text
            assert "Other platform item" not in youtube_page.text
            assert 'value="Video"' in youtube_page.text
            assert 'value="Extension"' not in youtube_page.text
            other_page = client.get("/?platform=其他")
            assert "Other platform item" in other_page.text
            assert "YouTube platform item" not in other_page.text

            platform_ascending = client.get("/?sort=platform_asc").text
            assert platform_ascending.index("YouTube platform item") < platform_ascending.index(
                "Other platform item"
            )
            platform_descending = client.get("/?sort=platform_desc").text
            assert platform_descending.index("Other platform item") < platform_descending.index(
                "YouTube platform item"
            )
            recently_updated = client.get("/?sort=updated_desc").text
            assert recently_updated.index("Other platform item") < recently_updated.index(
                "YouTube platform item"
            )

            monkeypatch.setattr(
                "app.main.extract_page",
                lambda url: ExtractionResult(
                    "example.com", "", "fetch_failed", "request timed out"
                ),
            )
            failed_capture = client.post(
                "/api/bookmarks",
                json={
                    "url": "https://example.com/offline",
                    "title": "Title captured by the extension",
                    "tags": ["Inbox"],
                },
            )
            assert failed_capture.status_code == 201
            assert failed_capture.json()["status"] == "fetch_failed"
            assert failed_capture.json()["title"] == "Title captured by the extension"
            unavailable_suggestions = client.post(
                f"/api/bookmarks/{failed_capture.json()['id']}/tag-suggestions"
            )
            assert unavailable_suggestions.status_code == 409

            monkeypatch.setenv("APP_USERNAME", "demo")
            monkeypatch.setenv("APP_PASSWORD", "correct horse battery staple")
            assert client.get("/").status_code == 401
            assert client.get("/health").status_code == 200
            credentials = base64.b64encode(
                b"demo:correct horse battery staple"
            ).decode()
            authenticated = client.get(
                "/", headers={"Authorization": f"Basic {credentials}"}
            )
            assert authenticated.status_code == 200
    finally:
        app.dependency_overrides.clear()
