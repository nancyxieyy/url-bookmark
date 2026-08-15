from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth import hash_extension_token
from app.database import get_session
from app.main import app
from app.models import Bookmark, ExtensionCredential
from app.schemas import ExtractionResult
from app.services.tag_recommender import TagSuggestions


def test_browser_capture_is_local_until_explicit_api_calls(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'browser-capture.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr("app.main.create_db_and_tables", lambda: None)
    monkeypatch.setattr("app.main.validate_url", lambda url: url.strip())

    def unexpected_server_fetch(_: str):
        raise AssertionError("browser capture must not call the server extractor")

    monkeypatch.setattr("app.main.extract_page", unexpected_server_fetch)
    recommendation_calls = []

    def fake_recommend(title, markdown, existing):
        recommendation_calls.append((title, markdown, existing))
        return TagSuggestions(existing_tags=[], new_tags=["Browser Capture"])

    monkeypatch.setattr("app.main.recommend_tags", fake_recommend)
    token = "browser-capture-token"
    headers = {"Authorization": f"Bearer {token}"}
    with Session(engine) as session:
        session.add(
            ExtensionCredential(id=1, token_hash=hash_extension_token(token))
        )
        session.commit()

    try:
        with TestClient(app) as client:
            duplicate_check = client.post(
                "/api/bookmarks/check-duplicate",
                headers=headers,
                json={
                    "url": "https://example.com/amp/article",
                },
            )
            assert duplicate_check.status_code == 200
            assert duplicate_check.json() == {"duplicate": False, "bookmark": None}
            with Session(engine) as session:
                assert session.exec(select(Bookmark)).all() == []
            assert recommendation_calls == []

            saved = client.post(
                "/api/bookmarks",
                headers=headers,
                json={
                    "url": "https://example.com/amp/article",
                    "title": "Browser-rendered article",
                    "markdown_content": "# Browser body\n\nRendered after login.",
                    "capture_method": "browser",
                    "tags": ["Private page"],
                    "notes": "Captured from the visible tab",
                },
            )
            assert saved.status_code == 201
            assert saved.json()["capture_method"] == "browser"
            with Session(engine) as session:
                bookmark = session.exec(select(Bookmark)).one()
                assert bookmark.markdown_content == "# Browser body\n\nRendered after login."
                assert bookmark.status == "success"
            assert recommendation_calls == []

            duplicate = client.post(
                "/api/bookmarks/check-duplicate",
                headers=headers,
                json={
                    "url": "https://example.com/amp/article#section",
                },
            )
            assert duplicate.json()["duplicate"] is True
            assert duplicate.json()["bookmark"]["id"] == saved.json()["id"]

            suggestions = client.post(
                "/api/bookmarks/browser-tag-suggestions",
                headers=headers,
                json={
                    "title": "Browser-rendered article",
                    "markdown_content": "# Browser body\n\nRendered after login.",
                },
            )
            assert suggestions.status_code == 200
            assert suggestions.json()["new_tags"] == ["Browser Capture"]
            assert len(recommendation_calls) == 1
    finally:
        app.dependency_overrides.clear()


def test_browser_url_only_capture_never_falls_back_to_server(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'url-only.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr("app.main.create_db_and_tables", lambda: None)
    monkeypatch.setattr("app.main.validate_url", lambda url: url.strip())
    monkeypatch.setattr(
        "app.main.extract_page",
        lambda _: (_ for _ in ()).throw(
            AssertionError("URL-only browser capture must not call extractor")
        ),
    )
    token = "url-only-token"
    headers = {"Authorization": f"Bearer {token}"}
    with Session(engine) as session:
        session.add(
            ExtensionCredential(id=1, token_hash=hash_extension_token(token))
        )
        session.commit()

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/bookmarks",
                headers=headers,
                json={
                    "url": "https://example.com/no-article",
                    "title": "URL only",
                    "markdown_content": "",
                    "capture_method": "browser",
                },
            )
            assert response.status_code == 201
            assert response.json()["status"] == "extract_failed"
            with Session(engine) as session:
                bookmark = session.exec(select(Bookmark)).one()
                assert bookmark.markdown_content == ""
                assert bookmark.capture_method == "browser"
    finally:
        app.dependency_overrides.clear()


def test_server_capture_still_uses_extractor(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'server-capture.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr("app.main.create_db_and_tables", lambda: None)
    monkeypatch.setattr("app.main.validate_url", lambda url: url.strip())
    fetched = []

    def fake_extract(url):
        fetched.append(url)
        return ExtractionResult("Server article", "# Server Markdown")

    monkeypatch.setattr("app.main.extract_page", fake_extract)
    token = "server-capture-token"
    headers = {"Authorization": f"Bearer {token}"}
    with Session(engine) as session:
        session.add(
            ExtensionCredential(id=1, token_hash=hash_extension_token(token))
        )
        session.commit()

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/bookmarks",
                headers=headers,
                json={"url": "https://example.com/server"},
            )
            assert response.status_code == 201
            assert response.json()["capture_method"] == "server"
            assert fetched == ["https://example.com/server"]
    finally:
        app.dependency_overrides.clear()
