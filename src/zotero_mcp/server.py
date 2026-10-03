"""MCP tools for a personal Zotero library and Word citation fields."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from zotero_mcp import __version__
from zotero_mcp.client import (
    READ_ERRORS,
    cited_items,
    failure,
    item_detail,
    list_collections,
    page,
    require_user_id,
    upload_file,
    valid_item_key,
    web_send,
    zotero_get,
)
from zotero_mcp.models import (
    UnconfiguredError,
    WordEmbedResult,
    ZoteroApiResult,
    ZoteroCollections,
    ZoteroItemResult,
    ZoteroPage,
)
from zotero_mcp.word import (
    EmbeddedItem,
    check_locale,
    check_paths,
    citation_keys,
    embed_document,
    style_id,
    style_name,
)

# Tools confined to the user's own library are closed-world. VS Code holds an
# open-world tool's results for the user's approval before the model sees them.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Any Web API request, DELETE included. It can also read public group libraries.
WEB_API_REQUEST = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
# If-None-Match: * stores a file only where none exists, so a repeat changes nothing.
FILE_UPLOAD = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
# Writes a new .docx, replacing an earlier output of the same name. The source is never changed.
WORD_OUTPUT = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

mcp = MCPServer(
    name="zotero",
    title="Zotero",
    version=__version__,
    instructions=(
        "Tools for the user's Zotero library through Web API v3. "
        "Reads use the local Zotero app when its library has items, and zotero.org otherwise. "
        "search_zotero, list_zotero_items, list_zotero_collections, and get_zotero_item are the bibliography helpers. "
        "Page with start and the returned next_start until next_start is null. "
        "Every result has a status: Found, Not_Found, OK, Unconfigured, or API_Error, with a message that explains it. "
        "zotero_api sends any other Web API request for this user. "
        "Writes go to api.zotero.org and sync back to the desktop app. "
        "Pass a relative path such as items, items/ITEMKEY, or collections/COLLECTIONKEY/items. "
        "groups lists the user's group libraries, and a path starting with groups/GROUPID/ reaches one. Key endpoints are refused. "
        "DELETE requires confirm_delete true. "
        "Updating or deleting one object needs its current version, in the body's version field or in if_unmodified_since_version; "
        "deleting several objects at once needs the library version. "
        "upload_zotero_file stores a local file on an existing attachment item. Create that attachment first with zotero_api. "
        "For a Microsoft Word file the Zotero plugin can refresh, put {{zotero:ITEMKEY}} markers in the .docx "
        "and call embed_zotero_word_fields. Put {{zotero:bibliography}} where the reference list should appear. "
        "File paths must be full paths. "
        "The API key is configured in the server environment. Do not ask the user for it and do not include it in arguments."
    ),
)


def _read_error(exc: Exception, *, start: int = 0, limit: int = 25) -> ZoteroPage:
    if isinstance(exc, UnconfiguredError):
        return ZoteroPage(status="Unconfigured", message=str(exc), start=start, limit=limit)
    return ZoteroPage(status="API_Error", message=failure(exc), start=start, limit=limit)


@mcp.tool(title="Search the Zotero library", annotations=READ_ONLY)
def search_zotero(
    query: Annotated[str, Field(description="Title, creator, or year. Zotero quick search treats this as one phrase.")],
    limit: Annotated[int, Field(ge=1, le=100, description="Page size, 1 to 100. Default 25.")] = 25,
    start: Annotated[int, Field(ge=0, description="Zero-based offset. Default 0. Use next_start from the previous page.")] = 0,
) -> ZoteroPage:
    """Search the user's Zotero library by title, creator, or year.

    Attachments, notes, and annotations are omitted. Results are one page;
    follow next_start until it is null.
    """
    text = query.strip()
    if not text:
        return ZoteroPage(status="Not_Found", message="No search text was provided.")
    try:
        payload, total, source = zotero_get(
            "items/top",
            {"q": text, "qmode": "titleCreatorYear", "limit": str(limit), "start": str(start), "format": "json"},
        )
        return page(
            payload,
            start=start,
            limit=limit,
            total_results=total,
            empty_message="No library item matched this search.",
            source=source,
        )
    except READ_ERRORS as exc:
        return _read_error(exc, start=start, limit=limit)


@mcp.tool(title="List Zotero library items", annotations=READ_ONLY)
def list_zotero_items(
    limit: Annotated[int, Field(ge=1, le=100, description="Page size, 1 to 100. Default 25.")] = 25,
    start: Annotated[int, Field(ge=0, description="Zero-based offset. Default 0. Use next_start from the previous page.")] = 0,
    collection_key: Annotated[str, Field(description="Optional 8-character collection key. Default empty, which lists the whole library.")] = "",
) -> ZoteroPage:
    """Page through bibliographic items in the library or in one collection."""
    collection = collection_key.strip()
    if collection and not valid_item_key(collection):
        return ZoteroPage(status="API_Error", message="collection_key must be an 8-character Zotero key.", start=start, limit=limit)
    path = f"collections/{collection}/items/top" if collection else "items/top"
    try:
        payload, total, source = zotero_get(
            path,
            {"limit": str(limit), "start": str(start), "sort": "title", "direction": "asc", "format": "json"},
        )
        return page(
            payload,
            start=start,
            limit=limit,
            total_results=total,
            empty_message="This page has no bibliographic items.",
            source=source,
        )
    except READ_ERRORS as exc:
        return _read_error(exc, start=start, limit=limit)


@mcp.tool(title="List Zotero collections", annotations=READ_ONLY)
def list_zotero_collections() -> ZoteroCollections:
    """List collections in the user's library, following Zotero's 100-item pages."""
    return list_collections()


@mcp.tool(title="Get one Zotero item", annotations=READ_ONLY)
def get_zotero_item(
    item_key: Annotated[str, Field(description="8-character Zotero item key from a search or list result.")],
) -> ZoteroItemResult:
    """Fetch one reference, including its abstract and a Vancouver bibliography line."""
    key = item_key.strip()
    if not valid_item_key(key):
        return ZoteroItemResult(status="API_Error", message="item_key must be an 8-character Zotero key.")
    try:
        payload, _total, source = zotero_get(
            f"items/{key}",
            {"include": "data,bib", "style": "vancouver", "linkwrap": "0", "format": "json"},
        )
    except LookupError:
        return ZoteroItemResult(status="Not_Found", message="No library item uses that key.")
    except UnconfiguredError as exc:
        return ZoteroItemResult(status="Unconfigured", message=str(exc))
    except READ_ERRORS as exc:
        return ZoteroItemResult(status="API_Error", message=failure(exc))
    if not isinstance(payload, dict):
        return ZoteroItemResult(status="API_Error", message="Zotero item response was not an object.")
    detail = item_detail(payload)
    if detail is None:
        return ZoteroItemResult(status="Not_Found", message="That key is not a bibliographic item.", source=source)
    origin = "the local Zotero app" if source == "local" else "zotero.org"
    return ZoteroItemResult(status="Found", message=f"Item fetched from {origin}.", source=source, item=detail)


def _query_value(value: Any) -> str:
    """Zotero query values are strings; accept the numbers and booleans models often send."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError("Query values must be strings, numbers, or true/false. Join several keys with commas.")


@mcp.tool(title="Call the Zotero Web API", annotations=WEB_API_REQUEST)
def zotero_api(
    method: Annotated[str, Field(description="GET, POST, PUT, PATCH, or DELETE.")],
    path: Annotated[str, Field(description="Relative Web API path. Examples: items, items/ITEMKEY, collections, collections/KEY/items, searches, tags, fulltext, deleted, groups, groups/GROUPID/items.")],
    query: Annotated[dict[str, Any] | None, Field(description="Query parameters, such as {\"limit\": 10, \"itemKey\": \"KEY1,KEY2\"}. Join several keys with commas.")] = None,
    body: Annotated[dict[str, Any] | list[dict[str, Any]] | None, Field(description="JSON object, or array of objects. Item creates are an array of item data. Include version when updating one object.")] = None,
    if_unmodified_since_version: Annotated[int | None, Field(description="Version precondition: the object's current version when updating or deleting one object, or the library version when deleting several.")] = None,
    write_token: Annotated[str | None, Field(description="Optional 32-character token. Repeating it prevents a successful create from running twice.")] = None,
    confirm_delete: Annotated[bool, Field(description="Must be true for DELETE. Default false, which refuses a delete.")] = False,
) -> ZoteroApiResult:
    """Send one Zotero Web API v3 request to the configured user library.

    Reads may still use the local app through the bibliography tools. This tool
    always uses api.zotero.org, including GET, so the response matches the
    account the API key can change. Create items with POST items and a JSON
    array; the result reports any objects Zotero rejected. Put collection keys
    inside each item's collections array. Update one item with PATCH
    items/ITEMKEY or PUT of the full item data, and send its current version.
    Delete with DELETE and confirm_delete true.
    """
    if method.strip().upper() == "DELETE" and not confirm_delete:
        return ZoteroApiResult(
            status="API_Error",
            message="DELETE was not sent. Pass confirm_delete true to delete Zotero objects.",
        )
    try:
        parameters = {name: _query_value(value) for name, value in (query or {}).items()}
    except ValueError as exc:
        return ZoteroApiResult(status="API_Error", message=str(exc))
    return web_send(
        method,
        path,
        query=parameters,
        body=body,
        if_unmodified_since_version=if_unmodified_since_version,
        write_token=write_token,
    )


@mcp.tool(title="Upload a file to a Zotero attachment", annotations=FILE_UPLOAD)
def upload_zotero_file(
    item_key: Annotated[str, Field(description="8-character key of an existing imported_file or imported_url attachment.")],
    file_path: Annotated[str, Field(description="Full path of the file on this computer.")],
) -> ZoteroApiResult:
    """Store a local file on an attachment item through the Web API upload flow.

    Create the attachment first with zotero_api. A new child attachment uses
    itemType attachment, linkMode imported_file, parentItem, and contentType.
    A file already stored with the same MD5 is left unchanged. An attachment
    that already holds a different file is not replaced: Zotero answers HTTP
    412. The upload limit here is 100 MB.
    """
    return upload_file(item_key, file_path)


@mcp.tool(title="Embed Zotero citation fields in a Word document", annotations=WORD_OUTPUT)
def embed_zotero_word_fields(
    docx_path: Annotated[str, Field(description="Full path of a .docx file containing {{zotero:ITEMKEY}} markers.")],
    output_path: Annotated[str, Field(description="Optional full .docx path to write. Empty writes a sibling named <name>.zotero.docx. The original is never overwritten.")] = "",
    style: Annotated[str, Field(description="CSL style short name, such as apa, or a zotero.org style URL. Default vancouver.")] = "vancouver",
    locale: Annotated[str, Field(description="Citation locale, such as en-GB. Default en-US.")] = "en-US",
    insert_bibliography: Annotated[bool, Field(description="Default true: append a Zotero bibliography field when the document has no {{zotero:bibliography}} marker.")] = True,
) -> WordEmbedResult:
    """Replace citation markers with Word fields the Zotero plugin can refresh.

    Markers: {{zotero:ITEMKEY}}, {{zotero:KEY1+KEY2}},
    {{zotero:ITEMKEY|locator=12|label=page|prefix=see|suffix=, emphasis added}},
    and {{zotero:bibliography}}. Open the result in Word and choose Zotero, Refresh.
    """
    source = Path(docx_path.strip()).expanduser()
    destination = Path(output_path.strip()).expanduser() if output_path.strip() else source.with_name(f"{source.stem}.zotero.docx")
    try:
        user_id = require_user_id()
        check_paths(source, destination)
        check_locale(locale)
        style_id(style)
        keys = citation_keys(source)
        fetched = cited_items(keys, style_name(style))
        stats = embed_document(
            source,
            destination,
            user_id=user_id,
            style=style,
            locale=locale,
            items={key: EmbeddedItem(csl=csl, bibliography=line) for key, (csl, line) in fetched.items()},
            insert_bibliography=insert_bibliography,
        )
    except UnconfiguredError as exc:
        return WordEmbedResult(status="Unconfigured", message=str(exc))
    except ValueError as exc:
        return WordEmbedResult(status="API_Error", message=str(exc))
    except PermissionError as exc:
        if exc.errno is None:
            return WordEmbedResult(status="API_Error", message=failure(exc))
        return WordEmbedResult(
            status="API_Error",
            message=f"{exc.strerror}: {exc.filename}. If the document is open in Word, close it and try again.",
        )
    except (*READ_ERRORS, OSError) as exc:
        return WordEmbedResult(status="API_Error", message=failure(exc))
    bibliography = " and a bibliography field" if stats.bibliography_inserted else ""
    return WordEmbedResult(
        status="OK",
        message=(
            f"Wrote {stats.citation_count} Zotero citation field(s){bibliography} to {stats.output_path.name}. "
            "Open it in Microsoft Word and use the Zotero tab, Refresh, to update the citation style."
        ),
        output_path=str(stats.output_path),
        style_id=stats.style_id,
        citation_count=stats.citation_count,
        bibliography_inserted=stats.bibliography_inserted,
    )
