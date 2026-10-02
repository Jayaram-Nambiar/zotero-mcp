"""Response models returned by the Zotero tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ZoteroItem(BaseModel):
    item_key: str
    item_type: str | None = None
    title: str
    creators: list[str] = Field(default_factory=list)
    date: str | None = None
    publication: str | None = None
    doi: str | None = None
    url: str | None = None


class ZoteroItemDetail(ZoteroItem):
    abstract: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    tags: list[str] = Field(default_factory=list)
    vancouver: str | None = None


class ZoteroApiResult(BaseModel):
    status: Literal["OK", "Unconfigured", "API_Error"]
    http_status: int = 0
    message: str
    last_modified_version: int | None = None
    body: Any = None


class ZoteroPage(BaseModel):
    status: Literal["Found", "Not_Found", "Unconfigured", "API_Error"]
    message: str
    source: Literal["local", "web"] | None = None
    total_results: int = 0
    start: int = 0
    limit: int = 25
    next_start: int | None = None
    matches: list[ZoteroItem] = Field(default_factory=list)


class ZoteroItemResult(BaseModel):
    status: Literal["Found", "Not_Found", "Unconfigured", "API_Error"]
    message: str
    source: Literal["local", "web"] | None = None
    item: ZoteroItemDetail | None = None


class ZoteroCollection(BaseModel):
    key: str
    name: str
    parent_key: str | None = None
    num_items: int | None = None


class ZoteroCollections(BaseModel):
    status: Literal["Found", "Not_Found", "Unconfigured", "API_Error"]
    message: str
    source: Literal["local", "web"] | None = None
    total_results: int = 0
    collections: list[ZoteroCollection] = Field(default_factory=list)


class WordEmbedResult(BaseModel):
    status: Literal["OK", "Unconfigured", "API_Error"]
    message: str
    output_path: str = ""
    style_id: str = ""
    citation_count: int = 0
    bibliography_inserted: bool = False


class UnconfiguredError(Exception):
    """The desktop app is unavailable and the web API credentials are missing."""
