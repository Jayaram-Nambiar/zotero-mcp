"""Zotero Web API v3 client.

Reads prefer the desktop app at http://127.0.0.1:23119/api and use
https://api.zotero.org when that library is empty or not running. Writes always
use api.zotero.org. The user ID and API key come from the process environment,
or on Windows from the user or system environment variables when the agent does
not pass them. The key is sent only as a header to api.zotero.org, never to a
host a response redirects to. It is never accepted as a tool argument and never
returned.
"""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

from zotero_mcp import __version__
from zotero_mcp.models import (
    UnconfiguredError,
    ZoteroApiResult,
    ZoteroCollection,
    ZoteroCollections,
    ZoteroItem,
    ZoteroItemDetail,
    ZoteroPage,
)

logger = logging.getLogger("zotero_mcp")

LOCAL_API = "http://127.0.0.1:23119/api"
WEB_API = "https://api.zotero.org"
USER_AGENT = f"zotero-mcp/{__version__} (https://github.com/Jayaram-Nambiar/zotero-mcp)"
LOCAL_TIMEOUT = 4
# Half the 60 seconds many clients allow a tool call, so a stalled request ends
# with the server's own error rather than the client's timeout.
WEB_TIMEOUT = 30
# A refused connection takes about two seconds on Windows, so a failed probe of
# the desktop app is not repeated for this long.
LOCAL_RETRY_SECONDS = 30
# Zotero accepts at most 50 keys in one itemKey filter.
BATCH_SIZE = 50
_RESPONSE_LIMIT = 60_000
_READ_LIMIT = 4 * 1024 * 1024
_UPLOAD_LIMIT = 100 * 1024 * 1024
_COLLECTION_LIMIT = 5_000
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_SKIP_TYPES = frozenset({"attachment", "note", "annotation"})
_KEY = re.compile(r"^[A-Za-z0-9]{8}$")
_CREDENTIAL_FORMATS = {
    "ZOTERO_USER_ID": re.compile(r"^[0-9]+$"),
    "ZOTERO_API_KEY": re.compile(r"^[A-Za-z0-9]+$"),
}
_TAG = re.compile(r"<[^>]+>")
# Zotero's schema maps these item-type fields onto title, date, and publicationTitle.
_TITLE_FIELDS = ("title", "caseName", "nameOfAct", "subject")
_DATE_FIELDS = ("date", "dateDecided", "dateEnacted", "issueDate")
_PUBLICATION_FIELDS = (
    "publicationTitle",
    "bookTitle",
    "proceedingsTitle",
    "websiteTitle",
    "blogTitle",
    "forumTitle",
    "encyclopediaTitle",
    "dictionaryTitle",
    "programTitle",
    "sessionTitle",
)
_WINDOWS_ENVIRONMENT = (
    ("HKEY_CURRENT_USER", "Environment"),
    ("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
)

_local_has_items = False
_local_retry_at = 0.0
_logged_empty_local = False


class _KeyStaysOnHost(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but drop the API key when one leads to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            redirected.remove_header("Zotero-api-key")
        return redirected


_opener = urllib.request.build_opener(_KeyStaysOnHost)

# What a read can raise once _request has mapped HTTP and network failures.
READ_ERRORS: tuple[type[Exception], ...] = (UnconfiguredError, LookupError, PermissionError, ConnectionError, ValueError)


def _windows_environment(name: str) -> str:
    """Return a variable as Windows stores it for new programs: the user value, then the system value."""
    if sys.platform != "win32":
        return ""
    import winreg

    for hive, path in _WINDOWS_ENVIRONMENT:
        try:
            with winreg.OpenKey(getattr(winreg, hive), path) as key:
                value, kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return winreg.ExpandEnvironmentStrings(value) if kind == winreg.REG_EXPAND_SZ else value
    return ""


def _credential(name: str) -> str:
    """Return ZOTERO_USER_ID or ZOTERO_API_KEY when it is well formed, or "".

    A user ID is digits and a key is letters and digits, so a placeholder such
    as YOUR_API_KEY or a reference the agent did not expand, such as
    ${env:ZOTERO_API_KEY}, counts as unset. The agent's environment wins. Some
    agents start servers without user variables (Claude Desktop) or with an
    environment from before they were set (Microsoft Store apps), so on Windows
    an unset value falls back to the stored user or system variable.
    """
    pattern = _CREDENTIAL_FORMATS[name]
    value = os.environ.get(name, "").strip()
    if not pattern.fullmatch(value):
        value = _windows_environment(name).strip()
    return value if pattern.fullmatch(value) else ""


def web_credentials() -> tuple[str, str] | None:
    """Return (user id, api key) when both values are usable."""
    user_id = _credential("ZOTERO_USER_ID")
    api_key = _credential("ZOTERO_API_KEY")
    if not user_id or not api_key:
        return None
    return user_id, api_key


def require_user_id() -> str:
    """Return the numeric zotero.org user id used in Word citation URIs."""
    user_id = _credential("ZOTERO_USER_ID")
    if not user_id:
        raise UnconfiguredError(
            "Set ZOTERO_USER_ID to the numeric user ID shown on "
            "https://www.zotero.org/settings/keys. Word matches citations to your "
            "library with that ID."
        )
    return user_id


def redact(value: str, secret: str) -> str:
    if secret and secret in value:
        return value.replace(secret, "[redacted]")
    return value


def api_target(path: str, user_id: str) -> str:
    """Return a relative API path. Absolute URLs and key endpoints are refused."""
    cleaned = path.strip()
    if cleaned.startswith(("http://", "https://")):
        raise ValueError("Pass a relative API path, not a full URL.")
    parts = [part for part in cleaned.strip("/").split("/") if part]
    if not parts or any(part in {".", ".."} or _PATH_PART.fullmatch(part) is None for part in parts):
        raise ValueError(
            "path must be a Zotero API path such as items, items/ITEMKEY, "
            "or collections/COLLECTIONKEY/items."
        )
    if parts[0] == "keys":
        raise ValueError(
            "Key endpoints are not exposed. The server uses the configured API key and does not return it."
        )
    if parts[0] == "groups" and len(parts) > 1:
        return "/".join(parts)
    return f"users/{user_id}/" + "/".join(parts)


def plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", value))).strip()


def _creator_name(creator: dict[str, Any]) -> str:
    if creator.get("name"):
        return str(creator["name"])
    parts = [str(creator.get("firstName") or "").strip(), str(creator.get("lastName") or "").strip()]
    return " ".join(part for part in parts if part)


def _first_field(data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        if data.get(field):
            return str(data[field])
    return None


def item_summary(record: dict[str, Any]) -> ZoteroItem | None:
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    item_type = str(data.get("itemType") or "")
    if item_type in _SKIP_TYPES:
        return None
    key = str(record.get("key") or data.get("key") or "")
    if not key:
        return None
    creators = data.get("creators") or []
    names = [_creator_name(creator) for creator in creators if isinstance(creator, dict)]
    return ZoteroItem(
        item_key=key,
        item_type=item_type or None,
        title=(_first_field(data, _TITLE_FIELDS) or "").strip(),
        creators=[name for name in names if name],
        date=_first_field(data, _DATE_FIELDS),
        publication=_first_field(data, _PUBLICATION_FIELDS),
        doi=str(data["DOI"]) if data.get("DOI") else None,
        url=str(data["url"]) if data.get("url") else None,
    )


def item_detail(record: dict[str, Any]) -> ZoteroItemDetail | None:
    summary = item_summary(record)
    if summary is None:
        return None
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    tags = data.get("tags") or []
    tag_names = [str(tag["tag"]) for tag in tags if isinstance(tag, dict) and tag.get("tag")]
    bib = record.get("bib")
    return ZoteroItemDetail(
        **summary.model_dump(),
        abstract=str(data["abstractNote"]).strip() or None if data.get("abstractNote") else None,
        volume=str(data["volume"]) if data.get("volume") else None,
        issue=str(data["issue"]) if data.get("issue") else None,
        pages=str(data["pages"]) if data.get("pages") else None,
        publisher=str(data["publisher"]) if data.get("publisher") else None,
        tags=tag_names,
        vancouver=plain_text(str(bib)) or None if isinstance(bib, str) else None,
    )


def _reason(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return str(reason) or type(reason).__name__


def _error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:2000]
    except (http.client.HTTPException, OSError):
        return ""
    finally:
        exc.close()


def _unreachable(verb: str, reason: str) -> str:
    message = f"Could not reach Zotero: {reason}"
    if verb != "GET":
        message += " The request may still have been applied, so check the library before you retry."
    return message


def _request(url: str, headers: dict[str, str], timeout: float) -> tuple[Any, int]:
    """GET JSON. HTTP and network failures become LookupError, PermissionError, or ConnectionError."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with _opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            total = response.headers.get("Total-Results")
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise LookupError("Zotero has no record at that key.") from exc
        if exc.code == 403:
            raise PermissionError("Zotero refused the request (HTTP 403).") from exc
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After", "")
            wait = f" Wait {retry_after} seconds and retry." if retry_after else " Retry later."
            raise ConnectionError(f"Zotero rate limit reached.{wait}") from exc
        raise ConnectionError(f"Zotero returned HTTP {exc.code}.") from exc
    except (http.client.HTTPException, OSError) as exc:
        raise ConnectionError(f"Could not reach Zotero: {_reason(exc)}") from exc
    total_results = int(total) if isinstance(total, str) and total.isdigit() else 0
    return payload, total_results


def _local_get(path: str, params: dict[str, str]) -> tuple[Any, int]:
    """Read the desktop app. No API key is sent. 127.0.0.1 avoids a slow IPv6 lookup."""
    query = urllib.parse.urlencode(params)
    url = f"{LOCAL_API}/users/0/{path}"
    if query:
        url = f"{url}?{query}"
    headers = {
        "Zotero-API-Version": "3",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    return _request(url, headers, LOCAL_TIMEOUT)


def _web_get(path: str, params: dict[str, str]) -> tuple[Any, int]:
    creds = web_credentials()
    if creds is None:
        raise UnconfiguredError(
            "The local Zotero app is not answering, and the web API is not configured. "
            "Start Zotero, or set ZOTERO_USER_ID and ZOTERO_API_KEY."
        )
    user_id, api_key = creds
    query = urllib.parse.urlencode(params)
    url = f"{WEB_API}/users/{user_id}/{path}"
    if query:
        url = f"{url}?{query}"
    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    return _request(url, headers, WEB_TIMEOUT)


def _local_library_ready() -> bool:
    """Use the desktop app only when it is up and its library contains items.

    An enabled but unsynced local database answers quickly with zero items.
    Treating that as authoritative would hide the zotero.org library. A probe
    that fails is not repeated for LOCAL_RETRY_SECONDS.
    """
    global _local_has_items, _local_retry_at, _logged_empty_local
    if _local_has_items:
        return True
    if time.monotonic() < _local_retry_at:
        return False
    try:
        _payload, total = _local_get("items", {"limit": "1", "format": "json"})
    except (LookupError, PermissionError, ConnectionError, ValueError) as exc:
        logger.info("Local Zotero API unavailable (%s); using zotero.org", exc)
        _local_retry_at = time.monotonic() + LOCAL_RETRY_SECONDS
        return False
    if total > 0:
        _local_has_items = True
        return True
    if not _logged_empty_local:
        logger.info("Local Zotero library has no items yet; using zotero.org until it syncs")
        _logged_empty_local = True
    return False


def zotero_get(path: str, params: dict[str, str]) -> tuple[Any, int, Literal["local", "web"]]:
    """Prefer the local app once its library has items. Otherwise use zotero.org.

    A 404 from the local app is not retried on the web: that record is not in the local library.
    """
    global _local_has_items, _local_retry_at
    if _local_library_ready():
        try:
            payload, total = _local_get(path, params)
            return payload, total, "local"
        except LookupError:
            raise
        except (PermissionError, ConnectionError, ValueError) as exc:
            logger.info("Local Zotero read failed (%s); using zotero.org", exc)
            _local_has_items = False
            _local_retry_at = time.monotonic() + LOCAL_RETRY_SECONDS
    payload, total = _web_get(path, params)
    return payload, total, "web"


def _via(source: Literal["local", "web"]) -> str:
    return "the local Zotero app" if source == "local" else "zotero.org"


def page(
    records: Any,
    *,
    start: int,
    limit: int,
    total_results: int,
    empty_message: str,
    source: Literal["local", "web"],
) -> ZoteroPage:
    if not isinstance(records, list):
        raise ValueError("Zotero items response was not a list")
    matches = [item for item in (item_summary(record) for record in records if isinstance(record, dict)) if item]
    next_start = start + limit if start + limit < total_results else None
    if matches:
        return ZoteroPage(
            status="Found",
            message=(
                f"{len(matches)} reference(s) in this page from {_via(source)}. "
                f"{total_results} matched in the library."
            ),
            source=source,
            total_results=total_results,
            start=start,
            limit=limit,
            next_start=next_start,
            matches=matches,
        )
    return ZoteroPage(
        status="Not_Found",
        message=empty_message,
        source=source,
        total_results=total_results,
        start=start,
        limit=limit,
        next_start=next_start,
    )


def failure(exc: Exception) -> str:
    logger.warning("Zotero request failed: %s", exc)
    return str(exc)


def _clip_body(payload: Any, secret: str) -> Any:
    encoded = redact(json.dumps(payload, ensure_ascii=False), secret)
    if len(encoded) <= _RESPONSE_LIMIT:
        return json.loads(encoded)
    return {"truncated": True, "preview": encoded[:_RESPONSE_LIMIT]}


def _response_body(raw: bytes, content_type: str, secret: str) -> tuple[Any, str]:
    """Return the parsed body and a note for the message. Binary content is described, not returned."""
    if not raw:
        return None, ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, f" The response is {content_type} content, which this tool does not return."
    if len(raw) > _READ_LIMIT:
        return {"truncated": True, "preview": redact(text[:_RESPONSE_LIMIT], secret)}, ""
    try:
        return _clip_body(json.loads(text), secret), ""
    except json.JSONDecodeError:
        if len(text) > _RESPONSE_LIMIT:
            return {"truncated": True, "preview": redact(text[:_RESPONSE_LIMIT], secret)}, ""
        return redact(text, secret), ""


def _write_outcome(parsed: Any) -> tuple[Literal["OK", "API_Error"], str]:
    """Report a multi-object write's failed objects, which Zotero returns with HTTP 200."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("failed"), dict) or not parsed["failed"]:
        return "OK", ""
    successful = parsed.get("successful") if isinstance(parsed.get("successful"), dict) else parsed.get("success")
    done = len(successful) if isinstance(successful, dict) else 0
    unchanged = len(parsed["unchanged"]) if isinstance(parsed.get("unchanged"), dict) else 0
    note = (
        f" {len(parsed['failed'])} object(s) failed, {done} succeeded, and {unchanged} were unchanged."
        " body.failed gives each failure's code and message."
    )
    return ("OK" if done or unchanged else "API_Error"), note


def _version_header(headers: Any) -> int | None:
    raw = headers.get("Last-Modified-Version") if headers is not None else None
    return int(raw) if isinstance(raw, str) and raw.isdigit() else None


def web_send(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    form: dict[str, str] | None = None,
    raw: bytes | None = None,
    content_type: str | None = None,
    if_unmodified_since_version: int | None = None,
    if_match: str | None = None,
    if_none_match: str | None = None,
    write_token: str | None = None,
) -> ZoteroApiResult:
    verb = method.strip().upper()
    if verb not in _METHODS:
        return ZoteroApiResult(status="API_Error", message="method must be GET, POST, PUT, PATCH, or DELETE.")
    creds = web_credentials()
    if creds is None:
        return ZoteroApiResult(
            status="Unconfigured",
            message="Zotero writes need ZOTERO_USER_ID and ZOTERO_API_KEY.",
        )
    user_id, api_key = creds
    try:
        relative = api_target(path, user_id)
    except ValueError as exc:
        return ZoteroApiResult(status="API_Error", message=str(exc))
    url = f"{WEB_API}/{relative}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    data: bytes | None = None
    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "User-Agent": USER_AGENT,
    }
    if body is not None and form is not None:
        return ZoteroApiResult(status="API_Error", message="Send JSON body or form fields, not both.")
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type or "application/octet-stream"
    if if_unmodified_since_version is not None:
        headers["If-Unmodified-Since-Version"] = str(if_unmodified_since_version)
    if if_match:
        headers["If-Match"] = if_match
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    if write_token:
        headers["Zotero-Write-Token"] = write_token
    request = urllib.request.Request(url, data=data, headers=headers, method=verb)
    try:
        with _opener.open(request, timeout=WEB_TIMEOUT) as response:
            status = response.status
            version = _version_header(response.headers)
            response_type = response.headers.get_content_type()
            length = response.headers.get("Content-Length", "")
            raw_body = response.read(_READ_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        detail = redact(_error_body(exc), api_key)
        logger.warning("Zotero %s %s failed: HTTP %s", verb, relative, exc.code)
        return ZoteroApiResult(
            status="API_Error",
            http_status=exc.code,
            message=detail or f"Zotero returned HTTP {exc.code}.",
            last_modified_version=_version_header(exc.headers),
        )
    except (http.client.HTTPException, OSError) as exc:
        logger.warning("Zotero %s %s failed: %s", verb, relative, exc)
        return ZoteroApiResult(status="API_Error", message=_unreachable(verb, _reason(exc)))
    # A sized read returns a cut-off body without raising, so compare it with Content-Length.
    if length.isdigit() and len(raw_body) < min(int(length), _READ_LIMIT + 1):
        logger.warning("Zotero %s %s response was cut off", verb, relative)
        return ZoteroApiResult(status="API_Error", http_status=status, message=_unreachable(verb, "the response was cut off."))
    parsed, note = _response_body(raw_body, response_type, api_key)
    outcome, failures = _write_outcome(parsed)
    return ZoteroApiResult(
        status=outcome,
        http_status=status,
        message=f"Zotero {verb} {relative} returned HTTP {status}.{note}{failures}",
        last_modified_version=version,
        body=parsed,
    )


def list_collections() -> ZoteroCollections:
    collected: list[ZoteroCollection] = []
    start = 0
    total = 0
    source: Literal["local", "web"] | None = None
    try:
        while start < _COLLECTION_LIMIT:
            payload, total, source = zotero_get(
                "collections",
                {"limit": "100", "start": str(start), "sort": "title", "format": "json"},
            )
            if not isinstance(payload, list) or not payload:
                break
            for record in payload:
                if not isinstance(record, dict):
                    continue
                data = record.get("data")
                if not isinstance(data, dict):
                    continue
                parent = data.get("parentCollection")
                meta = record.get("meta")
                num_items = meta.get("numItems") if isinstance(meta, dict) else None
                collected.append(
                    ZoteroCollection(
                        key=str(record.get("key") or data.get("key") or ""),
                        name=str(data.get("name") or ""),
                        parent_key=str(parent) if isinstance(parent, str) and parent else None,
                        num_items=int(num_items) if isinstance(num_items, int) else None,
                    )
                )
            start += 100
            if start >= total:
                break
    except READ_ERRORS as exc:
        if isinstance(exc, UnconfiguredError):
            return ZoteroCollections(status="Unconfigured", message=str(exc))
        return ZoteroCollections(status="API_Error", message=failure(exc))
    found = [item for item in collected if item.key and item.name]
    if not found:
        return ZoteroCollections(status="Not_Found", message="The library has no collections.", source=source, total_results=total)
    origin = _via(source) if source else "Zotero"
    shown = f"The first {len(found)} of {total}" if total > start else f"{len(found)}"
    return ZoteroCollections(
        status="Found",
        message=f"{shown} collection(s) from {origin}.",
        source=source,
        total_results=total or len(found),
        collections=found,
    )


def csl_item(payload: Any) -> dict[str, Any]:
    """Normalize a Zotero csljson export to one CSL item object."""
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ValueError("Zotero csljson export did not contain one item.")
    if isinstance(payload, dict) and isinstance(payload.get("items"), list) and payload["items"]:
        item = payload["items"][0]
        if isinstance(item, dict):
            return item
    if isinstance(payload, dict) and isinstance(payload.get("type"), str):
        return payload
    raise ValueError("Zotero csljson export was not a CSL item.")


def bibliography_line(record: Any) -> str:
    if not isinstance(record, dict):
        raise ValueError("Zotero bibliography response was not an item.")
    bib = record.get("bib")
    if not isinstance(bib, str) or not plain_text(bib):
        raise ValueError("Zotero did not return a bibliography line for that item.")
    return plain_text(bib)


def cited_items(keys: list[str], style: str) -> dict[str, tuple[dict[str, Any], str]]:
    """Return each item's CSL data and plain bibliography line in `style`, by item key.

    The desktop app answers one item at a time in milliseconds. zotero.org takes
    most of a second per request, so web reads fetch BATCH_SIZE items at once:
    a request per item would let a long document outlast the 60-second limit
    many MCP clients put on a tool call. If the desktop app stops answering
    partway, the remaining items are fetched from the web in batches.
    """
    found: dict[str, tuple[dict[str, Any], str]] = {}
    remaining = list(keys)
    while remaining and _local_library_ready():
        key = remaining.pop(0)
        found[key] = _cited_item(key, style)
    for index in range(0, len(remaining), BATCH_SIZE):
        chunk = remaining[index:index + BATCH_SIZE]
        records, _total = _web_get(
            "items",
            {
                "itemKey": ",".join(chunk),
                "include": "csljson,bib",
                "style": style,
                "linkwrap": "0",
                "format": "json",
                "limit": str(BATCH_SIZE),
            },
        )
        if not isinstance(records, list):
            raise ValueError("Zotero items response was not a list.")
        for record in records:
            key = record.get("key") if isinstance(record, dict) else None
            if key in chunk:
                found[key] = _item_parts(key, record.get("csljson"), record)
    missing = [key for key in keys if key not in found]
    if missing:
        raise LookupError("No library item uses " + ", ".join(missing) + ".")
    return {key: found[key] for key in keys}


def _cited_item(key: str, style: str) -> tuple[dict[str, Any], str]:
    try:
        csl_payload, _total, _source = zotero_get(f"items/{key}", {"format": "csljson"})
        bib_payload, _total, _source = zotero_get(
            f"items/{key}",
            {"include": "bib", "style": style, "linkwrap": "0", "format": "json"},
        )
    except LookupError:
        raise LookupError(f"No library item uses {key}.") from None
    return _item_parts(key, csl_payload, bib_payload)


def _item_parts(key: str, csl_payload: Any, bib_record: Any) -> tuple[dict[str, Any], str]:
    try:
        return csl_item(csl_payload), bibliography_line(bib_record)
    except ValueError as exc:
        raise ValueError(f"{key}: {exc}") from None


def valid_item_key(value: str) -> bool:
    return _KEY.fullmatch(value) is not None


def upload_file(item_key: str, file_path: str) -> ZoteroApiResult:
    """Store a local file on an attachment through the Web API upload flow.

    Zotero's upload handshake identifies the file with MD5. That digest is part
    of the documented protocol, not a password hash.
    """
    key = item_key.strip()
    if not valid_item_key(key):
        return ZoteroApiResult(status="API_Error", message="item_key must be an 8-character Zotero key.")
    path = Path(file_path.strip()).expanduser()
    if not path.is_absolute():
        return ZoteroApiResult(status="API_Error", message="file_path must be a full path, such as C:\\papers\\paper.pdf or /Users/you/paper.pdf.")
    if web_credentials() is None:
        return ZoteroApiResult(status="Unconfigured", message="Zotero uploads need ZOTERO_USER_ID and ZOTERO_API_KEY.")
    if not path.is_file():
        return ZoteroApiResult(status="API_Error", message="file_path is not a file on this computer.")
    try:
        stat = path.stat()
        if stat.st_size > _UPLOAD_LIMIT:
            return ZoteroApiResult(status="API_Error", message="The file is larger than the 100 MB upload limit.")
        payload = path.read_bytes()
    except OSError as exc:
        return ZoteroApiResult(status="API_Error", message=f"Could not read file_path: {exc.strerror or exc}")
    authorized = web_send(
        "POST",
        f"items/{key}/file",
        form={
            "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
            "filename": path.name,
            "filesize": str(len(payload)),
            "mtime": str(int(stat.st_mtime * 1000)),
        },
        if_none_match="*",
    )
    if authorized.status != "OK":
        return authorized
    upload = authorized.body if isinstance(authorized.body, dict) else {}
    if upload.get("exists") == 1:
        return ZoteroApiResult(status="OK", http_status=authorized.http_status, message="Zotero already has this file.", body={"exists": 1})
    upload_url = upload.get("url")
    upload_key = upload.get("uploadKey")
    if not isinstance(upload_url, str) or not isinstance(upload_key, str):
        return ZoteroApiResult(status="API_Error", message="Zotero did not return an upload URL.", body=upload)
    prefix = upload.get("prefix") or ""
    suffix = upload.get("suffix") or ""
    content_type = str(upload.get("contentType") or "application/octet-stream")
    stored = prefix.encode("utf-8") + payload + suffix.encode("utf-8") if isinstance(prefix, str) and isinstance(suffix, str) else payload
    request = urllib.request.Request(
        upload_url,
        data=stored,
        headers={"Content-Type": content_type, "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with _opener.open(request, timeout=WEB_TIMEOUT) as response:
            upload_status = response.status
    except urllib.error.HTTPError as exc:
        logger.warning("Zotero file upload failed: HTTP %s", exc.code)
        return ZoteroApiResult(status="API_Error", http_status=exc.code, message=_error_body(exc) or f"File upload returned HTTP {exc.code}.")
    except (http.client.HTTPException, OSError) as exc:
        logger.warning("Zotero file upload failed: %s", exc)
        return ZoteroApiResult(status="API_Error", message=f"Could not reach Zotero's file storage: {_reason(exc)}")
    if upload_status not in {200, 201, 204}:
        return ZoteroApiResult(status="API_Error", http_status=upload_status, message=f"File upload returned HTTP {upload_status}.")
    registered = web_send(
        "POST",
        f"items/{key}/file",
        form={"upload": upload_key},
        if_none_match="*",
    )
    if registered.status != "OK":
        return registered
    return ZoteroApiResult(
        status="OK",
        http_status=registered.http_status,
        message="File stored on the Zotero attachment.",
        last_modified_version=registered.last_modified_version,
    )
