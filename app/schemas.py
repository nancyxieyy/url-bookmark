from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class ExtractionResult:
    title: str
    markdown_content: str
    status: str = "success"
    error_message: str | None = None


class BookmarkCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)


class BookmarkResponse(BaseModel):
    id: int
    url: str
    title: str
    tags: list[str]
    status: str
    error_message: str | None
    duplicate: bool = False


class TagSuggestionsResponse(BaseModel):
    existing_tags: list[str]
    new_tags: list[str]
