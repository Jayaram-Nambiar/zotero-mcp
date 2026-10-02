"""Zotero Web API v3 client.

Reads prefer the desktop app at http://127.0.0.1:23119/api and use
https://api.zotero.org when that library is empty or not running. Writes always
use api.zotero.org. The user ID and API key come from the process environment,
or on Windows from the user or system environment variables when the agent does
not pass them. The key is sent only as a header. It is never accepted as a tool
argument and never returned.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import sys
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
WEB_TIMEOUT = 60
_RESPONSE_LIMIT = 60_000
_UPLOAD_LIMIT = 100 * 1024 * 1024
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_SKIP_TYPES = frozenset({"attachment", "note", "annotation"})
_KEY = re.compile(r"^[A-Za-z0-9]{8}$")
_TAG = re.compile(r"<[^>]+>")
_PLACEHOLDER = "YOUR_"
_WINDOWS_ENVIRONMENT = (
    ("HKEY_CURRENT_USER", "Environment"),
    ("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
)

_local_has_items = False
_logged_empty_local = False


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
    """Return ZOTERO_USER_ID or ZOTERO_API_KEY, or "" when it is unset or a placeholder.

    The agent's environment wins. Some agents start servers without user
    variables (Claude Desktop) or with an environment from before they were set
    (Microsoft Store apps), so on Windows a missing, empty, or placeholder value
    falls back to the stored user or system variable.
    """
    value = os.environ.get(name, "").strip()
    if not value or _PLACEHOLDER in value:
        value = _windows_environment(name).strip()
    return "" if _PLACEHOLDER in value else value


def web_credentials() -> tuple[str, str] | None:
    """Return (user id, api key) when both values are usable."""
    user_id = _credential("ZOTERO_USER_ID")
    api_key = _credential("ZOTERO_API_KEY")
    if not user_id.isdigit() or not api_key:
        return None
    return user_id, api_key


def require_user_id() -> str:
    """Return the numeric zotero.org user id used in Word citation URIs."""
    user_id = _credential("ZOTERO_USER_ID")
    if not user_id.isdigit():
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
    if parts[0] == "groups":
        return "/".join(parts)
    return f"users/{user_id}/" + "/".join(parts)


def plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", value))).strip()


def _creator_name(creator: dict[str, Any]) -> str:
    if creator.get("name"):
        return str(creator["name"])
    parts = [str(creator.get("firstName") or "").strip(), str(creator.get("lastName") or "").strip()]
    return " ".join(part for part in parts if part)


def item_summary(record: dict[str, Any]) -> ZoteroItem | None:
    data = record.get("data")
    if not isinstance(data, dict):
        return None
    item_type = str(data.get("itemType") or "")
    if item_type in _SKIP_TYPES:
        return None
    key = str(record.get("key") or data.get("key") or "")
    title = str(data.get("title") or "").strip()
    if not key or not title:
        return None
    creators = data.get("creators") or []
    names = [_creator_name(creator) for creator in creators if isinstance(creator, dict)]
    publication = data.get("publicationTitle") or data.get("bookTitle") or data.get("proceedingsTitle")
    return ZoteroItem(
        item_key=key,
        item_type=item_type or None,
        title=title,
        creators=[name for name in names if name],
        date=str(data["date"]) if data.get("date") else None,
        publication=str(publication) if publication else None,
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


def _request(url: str, headers: dict[str, str], timeout: float) -> tuple[Any, int]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            total = response.headers.get("Total-Results")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError("Zotero has no record at that key.") from exc
        if exc.code == 403:
            raise PermissionError("Zotero refused the request (HTTP 403).") from exc
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After", "")
            wait = f" Wait {retry_after} seconds and retry." if retry_after else " Retry later."
            raise ConnectionError(f"Zotero rate limit reached.{wait}") from exc
        raise ConnectionError(f"Zotero returned HTTP {exc.code}.") from exc
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
    Treating that as authoritative would hide the zotero.org library.
    """
    global _local_has_items, _logged_empty_local
    if _local_has_items:
        return True
    try:
        _payload, total = _local_get("items", {"limit": "1", "format": "json"})
    except (urllib.error.URLError, TimeoutError, PermissionError, ConnectionError, json.JSONDecodeError, ValueError) as exc:
        logger.info("Local Zotero API unavailable (%s); trying zotero.org", exc)
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
    if _local_library_ready():
        try:
            payload, total = _local_get(path, params)
            return payload, total, "local"
        except LookupError:
            raise
        except (urllib.error.URLError, TimeoutError, PermissionError, ConnectionError, json.JSONDecodeError, ValueError) as exc:
            logger.info("Local Zotero read failed (%s); trying zotero.org", exc)
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
    verb = method.upper()
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
        with urllib.request.urlopen(request, timeout=WEB_TIMEOUT) as response:
            raw_body = response.read()
            status = response.status
            version = _version_header(response.headers)
    except urllib.error.HTTPError as exc:
        detail = redact(exc.read().decode("utf-8", "replace")[:2000], api_key)
        logger.warning("Zotero %s %s failed: HTTP %s", verb, relative, exc.code)
        return ZoteroApiResult(
            status="API_Error",
            http_status=exc.code,
            message=detail or f"Zotero returned HTTP {exc.code}.",
            last_modified_version=_version_header(exc.headers),
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("Zotero %s %s failed: %s", verb, relative, exc)
        return ZoteroApiResult(status="API_Error", message=str(exc))
    parsed: Any = None
    if raw_body:
        text = raw_body.decode("utf-8", "replace")
        try:
            parsed = _clip_body(json.loads(text), api_key)
        except json.JSONDecodeError:
            parsed = redact(text[:_RESPONSE_LIMIT], api_key)
    return ZoteroApiResult(
        status="OK",
        http_status=status,
        message=f"Zotero {verb} {relative} returned HTTP {status}.",
        last_modified_version=version,
        body=parsed,
    )


def list_collections() -> ZoteroCollections:
    collected: list[ZoteroCollection] = []
    start = 0
    total = 0
    source: Literal["local", "web"] | None = None
    try:
        while start <= 1000:
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
    except UnconfiguredError as exc:
        return ZoteroCollections(status="Unconfigured", message=str(exc))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, LookupError, PermissionError, ConnectionError) as exc:
        return ZoteroCollections(status="API_Error", message=failure(exc))
    found = [item for item in collected if item.key and item.name]
    if not found:
        return ZoteroCollections(status="Not_Found", message="The library has no collections.", source=source, total_results=total)
    origin = _via(source) if source else "Zotero"
    return ZoteroCollections(
        status="Found",
        message=f"{len(found)} collection(s) from {origin}.",
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
    path = Path(file_path)
    if not path.is_file():
        return ZoteroApiResult(status="API_Error", message="file_path is not a file on this computer.")
    size = path.stat().st_size
    if size > _UPLOAD_LIMIT:
        return ZoteroApiResult(status="API_Error", message="The file is larger than the 100 MB upload limit.")
    payload = path.read_bytes()
    authorized = web_send(
        "POST",
        f"items/{key}/file",
        form={
            "md5": hashlib.md5(payload).hexdigest(),
            "filename": path.name,
            "filesize": str(size),
            "mtime": str(int(path.stat().st_mtime * 1000)),
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
        with urllib.request.urlopen(request, timeout=WEB_TIMEOUT) as response:
            upload_status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        logger.warning("Zotero file upload failed: HTTP %s", exc.code)
        return ZoteroApiResult(status="API_Error", http_status=exc.code, message=detail or f"File upload returned HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("Zotero file upload failed: %s", exc)
        return ZoteroApiResult(status="API_Error", message=str(exc))
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
