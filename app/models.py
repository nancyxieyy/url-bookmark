from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BookmarkTagLink(SQLModel, table=True):
    bookmark_id: int | None = Field(
        default=None, foreign_key="bookmark.id", primary_key=True
    )
    tag_id: int | None = Field(default=None, foreign_key="tag.id", primary_key=True)


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=50)

    bookmarks: list["Bookmark"] = Relationship(
        back_populates="tags", link_model=BookmarkTagLink
    )


class Bookmark(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True, max_length=2048)
    title: str = Field(index=True, max_length=500)
    markdown_content: str = Field(default="")
    status: str = Field(default="success", index=True, max_length=30)
    error_message: str | None = Field(default=None, max_length=1000)
    notes: str = Field(default="", max_length=5000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = Field(default=None, index=True)
    is_draft: bool = Field(default=False, index=True)

    tags: list[Tag] = Relationship(
        back_populates="bookmarks", link_model=BookmarkTagLink
    )
