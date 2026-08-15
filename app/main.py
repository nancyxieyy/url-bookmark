from __future__ import annotations

import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.database import create_db_and_tables, get_session
from app.models import Bookmark, Tag
from app.schemas import BookmarkCreateRequest, BookmarkResponse
from app.services.extractor import InvalidURLError, extract_page, validate_url


APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="URL Bookmark", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-p]{32}|moz-extension://[^/]+)$",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.middleware("http")
async def optional_basic_auth(request: Request, call_next):
    """Protect public deployments when APP_PASSWORD is configured."""
    if request.url.path == "/health":
        return await call_next(request)

    password = os.getenv("APP_PASSWORD", "")
    if not password:
        return await call_next(request)

    username = os.getenv("APP_USERNAME", "admin")
    expected = base64.b64encode(f"{username}:{password}".encode()).decode()
    authorization = request.headers.get("Authorization", "")
    if not secrets.compare_digest(authorization, f"Basic {expected}"):
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="URL Bookmark"'},
        )
    return await call_next(request)


def parse_tag_names(raw_tags: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_name in raw_tags.replace("，", ",").split(","):
        name = raw_name.strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name[:50])
    return result[:20]


def assign_tags(session: Session, bookmark: Bookmark, raw_tags: str) -> None:
    tags: list[Tag] = []
    for name in parse_tag_names(raw_tags):
        tag = session.exec(select(Tag).where(Tag.name == name)).first()
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        tags.append(tag)
    bookmark.tags = tags


def remove_orphan_tags(session: Session) -> None:
    for tag in session.exec(select(Tag)).all():
        if not tag.bookmarks:
            session.delete(tag)


def host_for(url: str) -> str:
    return urlparse(url).hostname or url


templates.env.globals["host_for"] = host_for


@app.get("/health")
def health():
    return {"status": "ok"}


def create_bookmark_record(
    session: Session,
    url: str,
    raw_tags: str,
    title_hint: str = "",
) -> Bookmark:
    normalized_url = validate_url(url)
    result = extract_page(normalized_url)
    fallback_title = title_hint.strip()[:500]
    bookmark = Bookmark(
        url=normalized_url,
        title=fallback_title if result.status != "success" and fallback_title else result.title,
        markdown_content=result.markdown_content,
        status=result.status,
        error_message=result.error_message,
    )
    assign_tags(session, bookmark, raw_tags)
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)
    return bookmark


@app.get("/")
def index(
    request: Request,
    q: str = "",
    tag: str = "",
    session: Session = Depends(get_session),
):
    statement = select(Bookmark).options(selectinload(Bookmark.tags))
    if q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Bookmark.title.ilike(pattern),
                Bookmark.url.ilike(pattern),
                Bookmark.markdown_content.ilike(pattern),
            )
        )
    if tag:
        statement = statement.where(Bookmark.tags.any(Tag.name == tag))
    bookmarks = session.exec(statement.order_by(Bookmark.created_at.desc())).all()
    tags = session.exec(select(Tag).order_by(Tag.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"bookmarks": bookmarks, "tags": tags, "q": q, "active_tag": tag},
    )


@app.post("/bookmarks")
def create_bookmark(
    url: str = Form(...),
    tags: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        normalized_url = validate_url(url)
    except InvalidURLError as exc:
        return RedirectResponse(f"/?error={quote_plus(str(exc))}", status_code=303)

    bookmark = create_bookmark_record(session, normalized_url, tags)
    message = "收藏成功。" if bookmark.status == "success" else "网址已收藏，但正文抓取失败，可稍后重试。"
    return RedirectResponse(f"/?message={quote_plus(message)}", status_code=303)


@app.get("/api/tags", response_model=list[str])
def api_tags(session: Session = Depends(get_session)):
    return [tag.name for tag in session.exec(select(Tag).order_by(Tag.name)).all()]


@app.post(
    "/api/bookmarks",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
def api_create_bookmark(
    payload: BookmarkCreateRequest,
    session: Session = Depends(get_session),
):
    try:
        bookmark = create_bookmark_record(
            session,
            payload.url,
            ",".join(payload.tags),
            title_hint=payload.title,
        )
    except InvalidURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BookmarkResponse(
        id=bookmark.id,
        url=bookmark.url,
        title=bookmark.title,
        tags=[tag.name for tag in bookmark.tags],
        status=bookmark.status,
        error_message=bookmark.error_message,
    )


@app.get("/bookmarks/{bookmark_id}")
def bookmark_detail(
    bookmark_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id)
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is None:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="bookmark_detail.html",
        context={"bookmark": bookmark},
    )


@app.get("/bookmarks/{bookmark_id}/edit")
def edit_bookmark_page(
    bookmark_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id)
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is None:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="edit.html",
        context={"bookmark": bookmark},
    )


@app.post("/bookmarks/{bookmark_id}/edit")
def update_bookmark(
    bookmark_id: int,
    title: str = Form(...),
    url: str = Form(...),
    tags: str = Form(""),
    session: Session = Depends(get_session),
):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    try:
        normalized_url = validate_url(url)
    except InvalidURLError as exc:
        return RedirectResponse(
            f"/bookmarks/{bookmark_id}/edit?error={quote_plus(str(exc))}", status_code=303
        )
    clean_title = title.strip()
    if not clean_title:
        return RedirectResponse(
            f"/bookmarks/{bookmark_id}/edit?error=标题不能为空", status_code=303
        )
    bookmark.title = clean_title[:500]
    bookmark.url = normalized_url
    bookmark.updated_at = datetime.now(timezone.utc)
    assign_tags(session, bookmark, tags)
    session.add(bookmark)
    session.commit()
    remove_orphan_tags(session)
    session.commit()
    return RedirectResponse(f"/bookmarks/{bookmark_id}?message=修改已保存", status_code=303)


@app.post("/bookmarks/{bookmark_id}/refetch")
def refetch_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    result = extract_page(bookmark.url)
    if result.status == "success":
        bookmark.title = result.title
        bookmark.markdown_content = result.markdown_content
    bookmark.status = result.status
    bookmark.error_message = result.error_message
    bookmark.updated_at = datetime.now(timezone.utc)
    session.add(bookmark)
    session.commit()
    message = "正文已重新抓取。" if result.status == "success" else "重新抓取失败，原有内容已保留。"
    return RedirectResponse(
        f"/bookmarks/{bookmark_id}?message={quote_plus(message)}", status_code=303
    )


@app.post("/bookmarks/{bookmark_id}/delete")
def delete_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is not None:
        session.delete(bookmark)
        session.commit()
        remove_orphan_tags(session)
        session.commit()
    return RedirectResponse("/?message=收藏已删除", status_code=303)
