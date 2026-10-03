"""Client behavior against fake Zotero servers on 127.0.0.1. Nothing here reaches the internet."""

from __future__ import annotations

import http.server
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from zotero_mcp import client
from zotero_mcp.server import list_zotero_collections, search_zotero, upload_zotero_file, zotero_api

_USER = "42"
_KEY = "FakeApiKey0123456789abcd"

Route = Callable[[http.server.BaseHTTPRequestHandler], None]


class _FakeHost:
    """An HTTP server on its own port. Routes map a URL path to a function that answers."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[dict[str, Any]] = []
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                url = urllib.parse.urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                host.requests.append(
                    {
                        "method": self.command,
                        "path": url.path,
                        "query": dict(urllib.parse.parse_qsl(url.query)),
                        "headers": {name.lower(): value for name, value in self.headers.items()},
                        "body": self.rfile.read(length) if length else b"",
                    }
                )
                route = host.routes.get(url.path)
                if route is None:
                    self.send_error(404)
                else:
                    route(self)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

            def log_message(self, *args: Any) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _FakeHost:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def _reply(status: int, body: bytes = b"", content_type: str = "application/json", headers: dict[str, str] | None = None) -> Route:
    def answer(handler: http.server.BaseHTTPRequestHandler) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(body)

    return answer


def _json(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> Route:
    return _reply(status, json.dumps(payload).encode("utf-8"), headers=headers)


def _hang_up(handler: http.server.BaseHTTPRequestHandler) -> None:
    handler.close_connection = True


def _truncated(handler: http.server.BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", "1000")
    handler.end_headers()
    handler.wfile.write(b'[{"key": ')
    handler.close_connection = True


def _item(key: str, title: str = "A title") -> dict[str, Any]:
    return {"key": key, "data": {"key": key, "itemType": "journalArticle", "title": title}}


class _Zotero(unittest.TestCase):
    """Point the client at fake hosts, with fake credentials and fresh read routing."""

    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.web = stack.enter_context(_FakeHost())
        self.local = stack.enter_context(_FakeHost())
        stack.enter_context(mock.patch.object(client, "WEB_API", self.web.url))
        stack.enter_context(mock.patch.object(client, "LOCAL_API", f"{self.local.url}/api"))
        # Proxy settings on the test machine must not reroute loopback requests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), client._KeyStaysOnHost)
        stack.enter_context(mock.patch.object(client, "_opener", opener))
        stack.enter_context(mock.patch.object(client, "_windows_environment", return_value=""))
        stack.enter_context(mock.patch.dict(os.environ, {"ZOTERO_USER_ID": _USER, "ZOTERO_API_KEY": _KEY}))
        stack.enter_context(mock.patch.object(client, "_local_has_items", False))
        stack.enter_context(mock.patch.object(client, "_local_retry_at", 0.0))
        stack.enter_context(mock.patch.object(client, "_logged_empty_local", False))
        stack.enter_context(mock.patch.object(client.logger, "disabled", True))

    def web_requests(self, path: str) -> list[dict[str, Any]]:
        return [request for request in self.web.requests if request["path"] == path]


class NetworkFailureTests(_Zotero):
    def test_a_dropped_connection_is_an_api_error(self) -> None:
        self.web.routes[f"/users/{_USER}/items/top"] = _hang_up
        self.web.routes[f"/users/{_USER}/items"] = _hang_up
        result = search_zotero("attention")
        self.assertEqual(result.status, "API_Error")
        self.assertIn("Could not reach Zotero", result.message)
        result = zotero_api("GET", "items")
        self.assertEqual(result.status, "API_Error")
        self.assertIn("Could not reach Zotero", result.message)
        # A write that lost its answer may still have been applied.
        result = zotero_api("POST", "items", body=[{"itemType": "book"}])
        self.assertIn("check the library before you retry", result.message)

    def test_a_truncated_response_is_an_api_error(self) -> None:
        self.web.routes[f"/users/{_USER}/items/top"] = _truncated
        self.web.routes[f"/users/{_USER}/items"] = _truncated
        self.assertEqual(search_zotero("attention").status, "API_Error")
        result = zotero_api("GET", "items")
        self.assertEqual(result.status, "API_Error")
        self.assertIn("cut off", result.message)

    def test_zoteros_error_message_is_returned_without_the_key(self) -> None:
        detail = f"Item has been modified since version 7 ({_KEY})".encode("utf-8")
        self.web.routes[f"/users/{_USER}/items/ABCD1234"] = _reply(412, detail, "text/plain", {"Last-Modified-Version": "9"})
        result = zotero_api("PATCH", "items/ABCD1234", body={"title": "New"}, if_unmodified_since_version=7)
        self.assertEqual((result.status, result.http_status, result.last_modified_version), ("API_Error", 412, 9))
        self.assertIn("modified since version 7", result.message)
        self.assertNotIn(_KEY, result.message)
        sent = self.web_requests(f"/users/{_USER}/items/ABCD1234")[0]["headers"]
        self.assertEqual(sent["if-unmodified-since-version"], "7")


class ReadRoutingTests(_Zotero):
    def test_a_404_from_the_desktop_app_falls_back_to_the_web(self) -> None:
        # Nothing is routed on the local host, so every local request gets 404.
        self.web.routes[f"/users/{_USER}/items/top"] = _json([_item("ABCD1234")], headers={"Total-Results": "1"})
        result = search_zotero("attention")
        self.assertEqual((result.status, result.source), ("Found", "web"))

    def test_a_failed_probe_is_not_repeated_until_the_wait_is_over(self) -> None:
        self.web.routes[f"/users/{_USER}/items/top"] = _json([_item("ABCD1234")], headers={"Total-Results": "1"})
        clock = mock.Mock(monotonic=mock.Mock(return_value=1000.0))
        with mock.patch.object(client, "_local_get", side_effect=ConnectionError("refused")) as local, mock.patch.object(client, "time", clock):
            search_zotero("one")
            search_zotero("two")
            self.assertEqual(local.call_count, 1)
            clock.monotonic.return_value = 1000.0 + client.LOCAL_RETRY_SECONDS + 1
            search_zotero("three")
            self.assertEqual(local.call_count, 2)

    def test_reads_switch_to_the_web_when_the_desktop_app_stops(self) -> None:
        self.web.routes[f"/users/{_USER}/items/top"] = _json([_item("ABCD1234")], headers={"Total-Results": "1"})
        with mock.patch.object(client, "_local_has_items", True), mock.patch.object(client, "_local_get", side_effect=ConnectionError("refused")) as local:
            self.assertEqual(search_zotero("one").source, "web")
            self.assertEqual(search_zotero("two").source, "web")
        self.assertEqual(local.call_count, 1)

    def test_collections_follow_every_page(self) -> None:
        names = [f"Collection {index:03d}" for index in range(250)]

        def pages(handler: http.server.BaseHTTPRequestHandler) -> None:
            start = int(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))["start"])
            records = [{"key": f"COLL{index:04d}", "data": {"name": names[index]}} for index in range(start, min(start + 100, 250))]
            _json(records, headers={"Total-Results": "250"})(handler)

        self.web.routes[f"/users/{_USER}/collections"] = pages
        result = list_zotero_collections()
        self.assertEqual((result.status, len(result.collections), result.total_results), ("Found", 250, 250))
        self.assertEqual(len(self.web_requests(f"/users/{_USER}/collections")), 3)
        with mock.patch.object(client, "_COLLECTION_LIMIT", 200):
            limited = list_zotero_collections()
        self.assertEqual(len(limited.collections), 200)
        self.assertIn("first 200 of 250", limited.message)


class WebRequestTests(_Zotero):
    def test_the_key_does_not_follow_a_redirect_to_another_host(self) -> None:
        with _FakeHost() as storage:
            storage.routes["/file.pdf"] = _reply(200, b"%PDF-1.7\n\xe2\xe3\xcf\xd3 binary", "application/pdf")
            self.web.routes[f"/users/{_USER}/items/ABCD1234/file"] = _reply(302, headers={"Location": f"{storage.url}/file.pdf"})
            result = zotero_api("GET", "items/ABCD1234/file")
        self.assertEqual(result.status, "OK")
        self.assertIsNone(result.body)
        self.assertIn("application/pdf", result.message)
        self.assertEqual(self.web_requests(f"/users/{_USER}/items/ABCD1234/file")[0]["headers"]["zotero-api-key"], _KEY)
        self.assertNotIn("zotero-api-key", storage.requests[0]["headers"])

    def test_the_key_follows_a_redirect_on_the_same_host(self) -> None:
        self.web.routes[f"/users/{_USER}/items/old"] = _reply(301, headers={"Location": f"{self.web.url}/users/{_USER}/items/new"})
        self.web.routes[f"/users/{_USER}/items/new"] = _json({"moved": True})
        result = zotero_api("GET", "items/old")
        self.assertEqual(result.body, {"moved": True})
        self.assertEqual(self.web_requests(f"/users/{_USER}/items/new")[0]["headers"]["zotero-api-key"], _KEY)

    def test_failed_objects_in_a_write_are_reported(self) -> None:
        partly = {"successful": {"0": {"key": "AAAA1111"}}, "success": {"0": "AAAA1111"}, "unchanged": {}, "failed": {"1": {"code": 400, "message": "Invalid item type"}}}
        self.web.routes[f"/users/{_USER}/items"] = _json(partly)
        result = zotero_api("POST", "items", body=[{"itemType": "book"}, {"itemType": "nonsense"}])
        self.assertEqual(result.status, "OK")
        self.assertIn("1 object(s) failed, 1 succeeded", result.message)
        self.web.routes[f"/users/{_USER}/items"] = _json({"successful": {}, "success": {}, "unchanged": {}, "failed": partly["failed"]})
        result = zotero_api("POST", "items", body=[{"itemType": "nonsense"}])
        self.assertEqual(result.status, "API_Error")
        self.assertEqual(result.body["failed"]["1"]["message"], "Invalid item type")


class UploadTests(_Zotero):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "paper.pdf"
        self.file.write_bytes(b"%PDF-1.7 test")

    def test_credentials_are_checked_before_the_file_is_read(self) -> None:
        with mock.patch.dict(os.environ, {"ZOTERO_API_KEY": ""}), mock.patch.object(Path, "read_bytes") as read:
            result = upload_zotero_file("ABCD1234", str(self.file))
        self.assertEqual(result.status, "Unconfigured")
        read.assert_not_called()

    def test_unreadable_files_and_relative_paths_are_api_errors(self) -> None:
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError(13, "Permission denied")):
            result = upload_zotero_file("ABCD1234", str(self.file))
        self.assertEqual(result.status, "API_Error")
        self.assertIn("Could not read file_path", result.message)
        self.assertIn("full path", upload_zotero_file("ABCD1234", "paper.pdf").message)

    def test_the_upload_handshake(self) -> None:
        with _FakeHost() as storage:
            storage.routes["/upload"] = _reply(201)
            answers = iter([
                _json({"url": f"{storage.url}/upload", "uploadKey": "UPLOADKEY", "prefix": "<", "suffix": ">", "contentType": "application/pdf"}),
                _reply(204, headers={"Last-Modified-Version": "12"}),
            ])
            self.web.routes[f"/users/{_USER}/items/ABCD1234/file"] = lambda handler: next(answers)(handler)
            result = upload_zotero_file("ABCD1234", str(self.file))
        self.assertEqual((result.status, result.last_modified_version), ("OK", 12))
        authorize, register = self.web_requests(f"/users/{_USER}/items/ABCD1234/file")
        self.assertEqual(authorize["headers"]["if-none-match"], "*")
        self.assertIn("md5=", authorize["body"].decode("ascii"))
        self.assertEqual(register["body"], b"upload=UPLOADKEY")
        self.assertEqual(storage.requests[0]["body"], b"<%PDF-1.7 test>")
        self.assertNotIn("zotero-api-key", storage.requests[0]["headers"])


class CitedItemTests(_Zotero):
    def _serve_batches(self, missing: set[str] = frozenset()) -> None:
        def batch(handler: http.server.BaseHTTPRequestHandler) -> None:
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))
            records = [
                {"key": key, "csljson": {"id": f"{_USER}/{key}", "type": "book", "title": key}, "bib": f"<div>{key}.</div>"}
                for key in query["itemKey"].split(",")
                if key not in missing
            ]
            _json(records)(handler)

        self.web.routes[f"/users/{_USER}/items"] = batch

    def test_web_reads_fetch_fifty_items_per_request(self) -> None:
        keys = [f"K{index:07d}" for index in range(120)]
        self._serve_batches()
        with mock.patch.object(client, "_local_library_ready", return_value=False):
            items = client.cited_items(keys, "apa")
        self.assertEqual(list(items), keys)
        self.assertEqual(items["K0000007"], ({"id": f"{_USER}/K0000007", "type": "book", "title": "K0000007"}, "K0000007."))
        batches = self.web_requests(f"/users/{_USER}/items")
        self.assertEqual([len(request["query"]["itemKey"].split(",")) for request in batches], [50, 50, 20])
        self.assertTrue(all(request["query"]["limit"] == "50" and request["query"]["style"] == "apa" for request in batches))

    def test_missing_items_are_named(self) -> None:
        self._serve_batches(missing={"BBBB2222"})
        with mock.patch.object(client, "_local_library_ready", return_value=False), self.assertRaises(LookupError) as raised:
            client.cited_items(["AAAA1111", "BBBB2222"], "apa")
        self.assertIn("BBBB2222", str(raised.exception))
        self.assertNotIn("AAAA1111", str(raised.exception))

    def test_items_left_when_the_desktop_app_stops_are_batched(self) -> None:
        self.local.routes["/api/users/0/items"] = _json([_item("AAAA1111")], headers={"Total-Results": "1"})
        self.local.routes["/api/users/0/items/AAAA1111"] = _hang_up

        def one_item(handler: http.server.BaseHTTPRequestHandler) -> None:
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))
            if query.get("format") == "csljson":
                _json([{"id": "AAAA1111", "type": "book"}])(handler)
            else:
                _json({"key": "AAAA1111", "bib": "<div>Book.</div>"})(handler)

        self.web.routes[f"/users/{_USER}/items/AAAA1111"] = one_item
        self._serve_batches()
        items = client.cited_items(["AAAA1111", "BBBB2222", "CCCC3333"], "apa")
        self.assertEqual(list(items), ["AAAA1111", "BBBB2222", "CCCC3333"])
        batches = self.web_requests(f"/users/{_USER}/items")
        self.assertEqual([request["query"]["itemKey"] for request in batches], ["BBBB2222,CCCC3333"])

    def test_the_desktop_app_is_read_item_by_item(self) -> None:
        self.local.routes["/api/users/0/items"] = _json([_item("AAAA1111")], headers={"Total-Results": "1"})

        def item(handler: http.server.BaseHTTPRequestHandler) -> None:
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))
            if query.get("format") == "csljson":
                _json([{"id": "AAAA1111", "type": "book"}])(handler)
            else:
                _json({"key": "AAAA1111", "bib": "<div>Book.</div>"})(handler)

        self.local.routes["/api/users/0/items/AAAA1111"] = item
        self.assertEqual(client.cited_items(["AAAA1111"], "apa"), {"AAAA1111": ({"id": "AAAA1111", "type": "book"}, "Book.")})
        with self.assertRaises(LookupError) as raised:
            client.cited_items(["ZZZZ9999"], "apa")
        self.assertIn("ZZZZ9999", str(raised.exception))
        self.assertEqual(self.web.requests, [])


if __name__ == "__main__":
    unittest.main()
