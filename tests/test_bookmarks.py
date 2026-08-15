from collections.abc import Generator
import base64

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.database import normalize_database_url
from app.main import app
from app.models import Bookmark
from app.schemas import ExtractionResult


def test_normalize_database_url_for_supabase():
    assert normalize_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert normalize_database_url("sqlite:///data/test.db") == "sqlite:///data/test.db"


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

    try:
        with TestClient(app) as client:
            response = client.post(
                "/bookmarks",
                data={"url": "https://example.com/article", "tags": "AI, Python"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            search = client.get("/?q=Searchable&tag=AI")
            assert search.status_code == 200
            assert "Test article" in search.text

            with Session(engine) as session:
                bookmark = session.exec(select(Bookmark)).one()
                bookmark_id = bookmark.id

            edit = client.post(
                f"/bookmarks/{bookmark_id}/edit",
                data={
                    "title": "Edited title",
                    "url": "https://example.com/edited",
                    "tags": "Product",
                },
                follow_redirects=False,
            )
            assert edit.status_code == 303

            detail = client.get(f"/bookmarks/{bookmark_id}")
            assert "Edited title" in detail.text
            assert "Product" in detail.text

            deleted = client.post(
                f"/bookmarks/{bookmark_id}/delete", follow_redirects=False
            )
            assert deleted.status_code == 303
            with Session(engine) as session:
                assert session.exec(select(Bookmark)).first() is None

            api_response = client.post(
                "/api/bookmarks",
                json={
                    "url": "https://example.com/from-extension",
                    "title": "Browser tab title",
                    "tags": ["Inbox", "Extension"],
                },
            )
            assert api_response.status_code == 201
            assert api_response.json()["title"] == "Test article"
            assert api_response.json()["tags"] == ["Inbox", "Extension"]

            tags_response = client.get("/api/tags")
            assert tags_response.status_code == 200
            assert tags_response.json() == ["Extension", "Inbox"]

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
