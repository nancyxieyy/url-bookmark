from __future__ import annotations

import base64
import math
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlsplit, urlunsplit

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

load_dotenv()

from app.database import create_db_and_tables, get_session
from app.models import Bookmark, Tag
from app.schemas import (
    BookmarkConfirmRequest,
    BookmarkCreateRequest,
    BookmarkResponse,
    TagSuggestionsResponse,
)
from app.services.extractor import InvalidURLError, extract_page, validate_url
from app.services.tag_recommender import TagRecommendationError, recommend_tags


APP_DIR = Path(__file__).resolve().parent
DEFAULT_TAG_CHOICES = ("Inbox", "稍后读", "AI", "技术", "学习", "工作")
TRASH_RETENTION_DAYS = 30
DRAFT_RETENTION_HOURS = 24


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
markdown_renderer = MarkdownIt("commonmark", {"html": False})


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


def available_tag_choices(session: Session) -> list[str]:
    choices = list(DEFAULT_TAG_CHOICES)
    seen = {choice.casefold() for choice in choices}
    for tag in session.exec(select(Tag).order_by(Tag.name)).all():
        if tag.name.casefold() not in seen:
            choices.append(tag.name)
            seen.add(tag.name.casefold())
    return choices


def merge_tag_fields(raw_tags: str, selected_tags: list[str]) -> str:
    return ",".join([raw_tags, *selected_tags])


def remove_orphan_tags(session: Session) -> None:
    for tag in session.exec(select(Tag)).all():
        if not tag.bookmarks:
            session.delete(tag)


def purge_expired_bookmarks(session: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRASH_RETENTION_DAYS)
    expired = session.exec(
        select(Bookmark)
        .where(Bookmark.deleted_at.is_not(None), Bookmark.deleted_at <= cutoff)
        .options(selectinload(Bookmark.tags))
    ).all()
    if not expired:
        return 0
    for bookmark in expired:
        session.delete(bookmark)
    session.commit()
    remove_orphan_tags(session)
    session.commit()
    return len(expired)


def purge_expired_drafts(session: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DRAFT_RETENTION_HOURS)
    drafts = session.exec(
        select(Bookmark)
        .where(Bookmark.is_draft.is_(True), Bookmark.updated_at <= cutoff)
        .options(selectinload(Bookmark.tags))
    ).all()
    if not drafts:
        return 0
    for bookmark in drafts:
        session.delete(bookmark)
    session.commit()
    remove_orphan_tags(session)
    session.commit()
    return len(drafts)


def trash_days_remaining(deleted_at: datetime) -> int:
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    expires_at = deleted_at + timedelta(days=TRASH_RETENTION_DAYS)
    seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return max(0, math.ceil(seconds / 86_400))


def host_for(url: str) -> str:
    return urlparse(url).hostname or url


def render_markdown(value: str) -> Markup:
    return Markup(markdown_renderer.render(value or ""))


def url_identity(url: str) -> str:
    """Return a stable comparison key without changing the URL we display."""
    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def find_active_bookmark_by_url(session: Session, url: str) -> Bookmark | None:
    exact = session.exec(
        select(Bookmark)
        .where(
            Bookmark.url == url,
            Bookmark.deleted_at.is_(None),
            Bookmark.is_draft.is_(False),
        )
        .options(selectinload(Bookmark.tags))
    ).first()
    if exact is not None:
        return exact
    identity = url_identity(url)
    bookmarks = session.exec(
        select(Bookmark)
        .where(Bookmark.deleted_at.is_(None), Bookmark.is_draft.is_(False))
        .options(selectinload(Bookmark.tags))
    ).all()
    return next(
        (bookmark for bookmark in bookmarks if url_identity(bookmark.url) == identity),
        None,
    )


templates.env.globals["host_for"] = host_for
templates.env.globals["trash_days_remaining"] = trash_days_remaining
templates.env.globals["render_markdown"] = render_markdown


@app.get("/health")
def health():
    return {"status": "ok"}


def create_bookmark_record(
    session: Session,
    url: str,
    raw_tags: str,
    title_hint: str = "",
    is_draft: bool = False,
    notes: str = "",
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
        is_draft=is_draft,
        notes=notes.strip()[:5000],
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
    suggest_for: int | None = None,
    duplicate_for: int | None = None,
    session: Session = Depends(get_session),
):
    purge_expired_bookmarks(session)
    purge_expired_drafts(session)
    statement = (
        select(Bookmark)
        .where(Bookmark.deleted_at.is_(None), Bookmark.is_draft.is_(False))
        .options(selectinload(Bookmark.tags))
    )
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
    tags = session.exec(
        select(Tag)
        .where(
            Tag.bookmarks.any(
                Bookmark.deleted_at.is_(None) & Bookmark.is_draft.is_(False)
            )
        )
        .order_by(Tag.name)
    ).all()
    preview = None
    if suggest_for is not None:
        preview = session.exec(
            select(Bookmark)
            .where(
                Bookmark.id == suggest_for,
                Bookmark.deleted_at.is_(None),
                Bookmark.is_draft.is_(True),
            )
            .options(selectinload(Bookmark.tags))
        ).first()
    duplicate = None
    if duplicate_for is not None:
        duplicate = session.exec(
            select(Bookmark)
            .where(
                Bookmark.id == duplicate_for,
                Bookmark.deleted_at.is_(None),
                Bookmark.is_draft.is_(False),
            )
            .options(selectinload(Bookmark.tags))
        ).first()
    capture_bookmark = duplicate or preview
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "bookmarks": bookmarks,
            "tags": tags,
            "tag_choices": available_tag_choices(session),
            "selected_tags": set(),
            "capture_bookmark": capture_bookmark,
            "capture_is_duplicate": duplicate is not None,
            "capture_tag_choices": available_tag_choices(session),
            "capture_selected_tags": (
                {item.name for item in capture_bookmark.tags}
                if capture_bookmark
                else set()
            ),
            "q": q,
            "active_tag": tag,
        },
    )


@app.post("/bookmarks/preview")
def preview_bookmark(
    url: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        normalized_url = validate_url(url)
    except InvalidURLError as exc:
        return RedirectResponse(f"/?error={quote_plus(str(exc))}", status_code=303)

    duplicate = find_active_bookmark_by_url(session, normalized_url)
    if duplicate is not None:
        return RedirectResponse(
            f"/?duplicate_for={duplicate.id}&message="
            f"{quote_plus('该网址已收藏过，可以修改标签。')}#capture",
            status_code=303,
        )

    bookmark = create_bookmark_record(
        session,
        normalized_url,
        "",
        is_draft=True,
    )
    message = (
        "正文已抓取，请选择标签后收藏。"
        if bookmark.status == "success"
        else "网址已读取，但正文抓取失败；仍可添加标签并收藏。"
    )
    return RedirectResponse(
        f"/?suggest_for={bookmark.id}&message={quote_plus(message)}#capture",
        status_code=303,
    )


@app.post("/bookmarks")
def create_bookmark(
    url: str = Form(...),
    tags: str = Form(""),
    tag_choices: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    try:
        normalized_url = validate_url(url)
    except InvalidURLError as exc:
        return RedirectResponse(f"/?error={quote_plus(str(exc))}", status_code=303)

    duplicate = find_active_bookmark_by_url(session, normalized_url)
    if duplicate is not None:
        return RedirectResponse(
            f"/?duplicate_for={duplicate.id}&message="
            f"{quote_plus('该网址已收藏过，可以修改标签。')}#capture",
            status_code=303,
        )

    bookmark = create_bookmark_record(
        session, normalized_url, merge_tag_fields(tags, tag_choices)
    )
    message = (
        "收藏成功。"
        if bookmark.status == "success"
        else "网址已收藏，但正文抓取失败，可稍后重试。"
    )
    return RedirectResponse(f"/?message={quote_plus(message)}", status_code=303)


@app.get("/api/tags", response_model=list[str])
def api_tags(session: Session = Depends(get_session)):
    return [
        tag.name
        for tag in session.exec(
            select(Tag)
            .where(
                Tag.bookmarks.any(
                    Bookmark.deleted_at.is_(None) & Bookmark.is_draft.is_(False)
                )
            )
            .order_by(Tag.name)
        ).all()
    ]


@app.post(
    "/api/bookmarks/{bookmark_id}/tag-suggestions",
    response_model=TagSuggestionsResponse,
)
def api_tag_suggestions(
    bookmark_id: int,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id)
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="收藏不存在。")
    if bookmark.deleted_at is not None:
        raise HTTPException(status_code=409, detail="回收站中的收藏不能生成标签推荐。")
    if bookmark.status != "success" or not bookmark.markdown_content.strip():
        raise HTTPException(status_code=409, detail="正文抓取成功后才能生成标签推荐。")

    library_tags = [
        tag.name for tag in session.exec(select(Tag).order_by(Tag.name)).all()
    ]
    try:
        suggestions = recommend_tags(
            bookmark.title,
            bookmark.markdown_content,
            library_tags,
        )
    except TagRecommendationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    selected = {tag.name.casefold() for tag in bookmark.tags}
    return TagSuggestionsResponse(
        existing_tags=[
            tag for tag in suggestions.existing_tags if tag.casefold() not in selected
        ],
        new_tags=[tag for tag in suggestions.new_tags if tag.casefold() not in selected],
    )


@app.post("/bookmarks/{bookmark_id}/tags")
def update_bookmark_tags(
    bookmark_id: int,
    tags: str = Form(""),
    tag_choices: list[str] = Form([]),
    duplicate: bool = False,
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.deleted_at is not None:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    assign_tags(session, bookmark, merge_tag_fields(tags, tag_choices))
    bookmark.is_draft = False
    bookmark.notes = notes.strip()[:5000]
    bookmark.updated_at = datetime.now(timezone.utc)
    session.add(bookmark)
    session.commit()
    remove_orphan_tags(session)
    session.commit()
    message = "标签已更新" if duplicate else "收藏成功"
    return RedirectResponse(f"/?message={quote_plus(message)}#library", status_code=303)


@app.post("/bookmarks/{bookmark_id}/discard")
def discard_bookmark_draft(
    bookmark_id: int,
    session: Session = Depends(get_session),
):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is not None and bookmark.is_draft:
        session.delete(bookmark)
        session.commit()
        remove_orphan_tags(session)
        session.commit()
    return RedirectResponse("/#capture", status_code=303)


def serialize_bookmark(bookmark: Bookmark, *, duplicate: bool = False) -> BookmarkResponse:
    return BookmarkResponse(
        id=bookmark.id,
        url=bookmark.url,
        title=bookmark.title,
        tags=[tag.name for tag in bookmark.tags],
        status=bookmark.status,
        error_message=bookmark.error_message,
        notes=bookmark.notes,
        duplicate=duplicate,
    )


@app.post(
    "/api/bookmarks/preview",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
def api_preview_bookmark(
    payload: BookmarkCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
):
    try:
        normalized_url = validate_url(payload.url)
    except InvalidURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = find_active_bookmark_by_url(session, normalized_url)
    if duplicate is not None:
        response.status_code = status.HTTP_200_OK
        return serialize_bookmark(duplicate, duplicate=True)
    bookmark = create_bookmark_record(
        session,
        normalized_url,
        "",
        title_hint=payload.title,
        is_draft=True,
        notes=payload.notes,
    )
    return serialize_bookmark(bookmark)


@app.post("/api/bookmarks/{bookmark_id}/confirm", response_model=BookmarkResponse)
def api_confirm_bookmark(
    bookmark_id: int,
    payload: BookmarkConfirmRequest,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id, Bookmark.deleted_at.is_(None))
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is None:
        raise HTTPException(status_code=404, detail="收藏不存在。")
    assign_tags(session, bookmark, ",".join(payload.tags))
    bookmark.notes = payload.notes.strip()[:5000]
    bookmark.is_draft = False
    bookmark.updated_at = datetime.now(timezone.utc)
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)
    remove_orphan_tags(session)
    session.commit()
    return serialize_bookmark(bookmark)


@app.get("/api/bookmarks/recent", response_model=list[BookmarkResponse])
def api_recent_bookmarks(
    limit: int = 3,
    session: Session = Depends(get_session),
):
    safe_limit = max(1, min(limit, 10))
    bookmarks = session.exec(
        select(Bookmark)
        .where(Bookmark.deleted_at.is_(None), Bookmark.is_draft.is_(False))
        .options(selectinload(Bookmark.tags))
        .order_by(Bookmark.created_at.desc())
        .limit(safe_limit)
    ).all()
    return [serialize_bookmark(bookmark) for bookmark in bookmarks]


@app.post("/api/bookmarks/{bookmark_id}/delete")
def api_delete_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.deleted_at is not None or bookmark.is_draft:
        raise HTTPException(status_code=404, detail="收藏不存在。")
    bookmark.deleted_at = datetime.now(timezone.utc)
    bookmark.updated_at = bookmark.deleted_at
    session.add(bookmark)
    session.commit()
    return {"ok": True}


@app.post(
    "/api/bookmarks",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
def api_create_bookmark(
    payload: BookmarkCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
):
    try:
        normalized_url = validate_url(payload.url)
        duplicate = find_active_bookmark_by_url(session, normalized_url)
        if duplicate is not None:
            existing_tags = [tag.name for tag in duplicate.tags]
            assign_tags(
                session,
                duplicate,
                ",".join([*existing_tags, *payload.tags]),
            )
            duplicate.updated_at = datetime.now(timezone.utc)
            if payload.notes.strip():
                duplicate.notes = payload.notes.strip()[:5000]
            session.add(duplicate)
            session.commit()
            session.refresh(duplicate)
            response.status_code = status.HTTP_200_OK
            return BookmarkResponse(
                id=duplicate.id,
                url=duplicate.url,
                title=duplicate.title,
                tags=[tag.name for tag in duplicate.tags],
                status=duplicate.status,
                error_message=duplicate.error_message,
                notes=duplicate.notes,
                duplicate=True,
            )
        bookmark = create_bookmark_record(
            session,
            normalized_url,
            ",".join(payload.tags),
            title_hint=payload.title,
            notes=payload.notes,
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
        notes=bookmark.notes,
        duplicate=False,
    )


@app.get("/bookmarks/{bookmark_id}")
def bookmark_detail(
    bookmark_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(
            Bookmark.id == bookmark_id,
            Bookmark.deleted_at.is_(None),
            Bookmark.is_draft.is_(False),
        )
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
        .where(
            Bookmark.id == bookmark_id,
            Bookmark.deleted_at.is_(None),
            Bookmark.is_draft.is_(False),
        )
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is None or bookmark.deleted_at is not None or bookmark.is_draft:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="edit.html",
        context={
            "bookmark": bookmark,
            "tag_choices": available_tag_choices(session),
            "selected_tags": {tag.name for tag in bookmark.tags},
        },
    )


@app.post("/bookmarks/{bookmark_id}/edit")
def update_bookmark(
    bookmark_id: int,
    title: str = Form(...),
    url: str = Form(...),
    tags: str = Form(""),
    tag_choices: list[str] = Form([]),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.deleted_at is not None or bookmark.is_draft:
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
    bookmark.notes = notes.strip()[:5000]
    assign_tags(session, bookmark, merge_tag_fields(tags, tag_choices))
    session.add(bookmark)
    session.commit()
    remove_orphan_tags(session)
    session.commit()
    return RedirectResponse(f"/bookmarks/{bookmark_id}?message=修改已保存", status_code=303)


@app.post("/bookmarks/{bookmark_id}/note")
def update_bookmark_note(
    bookmark_id: int,
    notes: str = Form(""),
    action: str = Form("save"),
    session: Session = Depends(get_session),
):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.deleted_at is not None or bookmark.is_draft:
        return RedirectResponse("/?error=收藏不存在", status_code=303)
    bookmark.notes = "" if action == "delete" else notes.strip()[:5000]
    bookmark.updated_at = datetime.now(timezone.utc)
    session.add(bookmark)
    session.commit()
    message = "备注已删除" if action == "delete" else "备注已保存"
    return RedirectResponse(
        f"/bookmarks/{bookmark_id}?message={quote_plus(message)}#notes",
        status_code=303,
    )


@app.post("/bookmarks/{bookmark_id}/refetch")
def refetch_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.deleted_at is not None or bookmark.is_draft:
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
    if bookmark is not None and bookmark.deleted_at is None and not bookmark.is_draft:
        bookmark.deleted_at = datetime.now(timezone.utc)
        bookmark.updated_at = bookmark.deleted_at
        session.add(bookmark)
        session.commit()
    return RedirectResponse("/?message=收藏已移入回收站", status_code=303)


@app.get("/trash")
def trash_page(request: Request, session: Session = Depends(get_session)):
    purged_count = purge_expired_bookmarks(session)
    bookmarks = session.exec(
        select(Bookmark)
        .where(Bookmark.deleted_at.is_not(None), Bookmark.is_draft.is_(False))
        .options(selectinload(Bookmark.tags))
        .order_by(Bookmark.deleted_at.desc())
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="trash.html",
        context={"bookmarks": bookmarks, "purged_count": purged_count},
    )


@app.post("/bookmarks/{bookmark_id}/restore")
def restore_bookmark(bookmark_id: int, session: Session = Depends(get_session)):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is not None and bookmark.deleted_at is not None:
        bookmark.deleted_at = None
        bookmark.updated_at = datetime.now(timezone.utc)
        session.add(bookmark)
        session.commit()
    return RedirectResponse("/trash?message=收藏已恢复", status_code=303)


@app.post("/bookmarks/{bookmark_id}/permanent-delete")
def permanently_delete_bookmark(
    bookmark_id: int,
    session: Session = Depends(get_session),
):
    bookmark = session.exec(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id, Bookmark.deleted_at.is_not(None))
        .options(selectinload(Bookmark.tags))
    ).first()
    if bookmark is not None:
        session.delete(bookmark)
        session.commit()
        remove_orphan_tags(session)
        session.commit()
    return RedirectResponse("/trash?message=收藏已彻底删除", status_code=303)
