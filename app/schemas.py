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
    notes: str = Field(default="", max_length=5000)
    markdown_content: str = Field(default="", max_length=1_000_000)
    capture_method: str = Field(default="server", pattern="^(server|browser)$")
    replace_existing: bool = False


class BookmarkDuplicateCheckRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class BrowserTagSuggestionsRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    markdown_content: str = Field(min_length=1, max_length=1_000_000)


class BookmarkConfirmRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=5000)


class BookmarkResponse(BaseModel):
    id: int
    url: str
    title: str
    tags: list[str]
    status: str
    error_message: str | None
    notes: str = ""
    duplicate: bool = False
    capture_method: str = "server"


class BookmarkDuplicateCheckResponse(BaseModel):
    duplicate: bool
    bookmark: BookmarkResponse | None = None


class TagSuggestionsResponse(BaseModel):
    existing_tags: list[str]
    new_tags: list[str]
