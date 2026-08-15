from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from app.database import get_session
from app.models import ExtensionCredential


EXTENSION_CREDENTIAL_ID = 1
DUMMY_TOKEN_HASH = "0" * 64


def expected_basic_authorization() -> str | None:
    password = os.getenv("APP_PASSWORD", "")
    if not password:
        return None
    username = os.getenv("APP_USERNAME", "admin")
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def valid_basic_authorization(authorization: str) -> bool:
    expected = expected_basic_authorization()
    return expected is None or secrets.compare_digest(authorization, expected)


def hash_extension_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_extension_token(
    session: Session,
) -> tuple[ExtensionCredential, str]:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    credential = session.get(ExtensionCredential, EXTENSION_CREDENTIAL_ID)
    if credential is None:
        credential = ExtensionCredential(
            id=EXTENSION_CREDENTIAL_ID,
            token_hash=hash_extension_token(raw_token),
            created_at=now,
            regenerated_at=now,
        )
    else:
        credential.token_hash = hash_extension_token(raw_token)
        credential.regenerated_at = now
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return credential, raw_token


def extension_token_is_valid(session: Session, raw_token: str) -> bool:
    credential = session.get(ExtensionCredential, EXTENSION_CREDENTIAL_ID)
    expected_hash = credential.token_hash if credential else DUMMY_TOKEN_HASH
    supplied_hash = hash_extension_token(raw_token)
    return secrets.compare_digest(supplied_hash, expected_hash)


def require_extension_token(
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, raw_token = authorization.partition(" ")
    valid = (
        separator == " "
        and scheme.casefold() == "bearer"
        and bool(raw_token.strip())
        and extension_token_is_valid(session, raw_token.strip())
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Extension API Token 无效或未配置。",
            headers={"WWW-Authenticate": "Bearer"},
        )
