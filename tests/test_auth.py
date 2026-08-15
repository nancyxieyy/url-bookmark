import base64
import re
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.auth import hash_extension_token
from app.database import get_session
from app.main import app
from app.models import ExtensionCredential


def basic_header(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def revealed_token(html: str) -> str:
    match = re.search(r"<code data-token-value>([^<]+)</code>", html)
    assert match is not None
    return match.group(1).strip()


def test_extension_token_lifecycle_and_permission_boundary(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr("app.main.create_db_and_tables", lambda: None)
    monkeypatch.setenv("APP_USERNAME", "owner")
    monkeypatch.setenv("APP_PASSWORD", "a-long-test-password")
    web_auth = basic_header("owner", "a-long-test-password")

    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/").status_code == 401
            assert client.get("/", headers=web_auth).status_code == 200

            assert client.get("/api/tags").status_code == 401
            assert client.get(
                "/api/tags", headers={"Authorization": "Bearer wrong"}
            ).status_code == 401

            generated = client.post(
                "/settings/extension-token/generate", headers=web_auth
            )
            assert generated.status_code == 200
            first_token = revealed_token(generated.text)
            assert first_token not in client.get("/settings", headers=web_auth).text
            with Session(engine) as session:
                credential = session.get(ExtensionCredential, 1)
                assert credential is not None
                assert credential.token_hash == hash_extension_token(first_token)
                assert credential.token_hash != first_token

            first_auth = {"Authorization": f"Bearer {first_token}"}
            assert client.get("/api/tags", headers=first_auth).status_code == 200

            forbidden = client.post(
                "/settings/extension-token/regenerate", headers=first_auth
            )
            assert forbidden.status_code == 401

            regenerated = client.post(
                "/settings/extension-token/regenerate", headers=web_auth
            )
            assert regenerated.status_code == 200
            second_token = revealed_token(regenerated.text)
            assert second_token != first_token
            assert client.get("/api/tags", headers=first_auth).status_code == 401
            assert client.get(
                "/api/tags",
                headers={"Authorization": f"Bearer {second_token}"},
            ).status_code == 200

            preflight = client.options(
                "/api/tags",
                headers={
                    "Origin": f"chrome-extension://{'b' * 32}",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"].startswith(
                "chrome-extension://"
            )
            assert "authorization" in preflight.headers[
                "access-control-allow-headers"
            ].lower()
    finally:
        app.dependency_overrides.clear()
