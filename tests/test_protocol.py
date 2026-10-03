"""Talk to the server over stdio the way MCP clients do. Nothing here calls Zotero."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import unittest
from typing import Any

from zotero_mcp import __version__

try:
    from jsonschema import Draft202012Validator
except ImportError:  # mcp depends on jsonschema, so this is only a safeguard.
    Draft202012Validator = None

# Every protocol revision that clients negotiate with initialize, oldest first.
_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
# The tool-name rule shared by the Anthropic, OpenAI, and Gemini tool APIs.
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TIMEOUT = 60

# Calls that return before any network access, and the status each must report.
_OFFLINE_CALLS = (
    ("search_zotero", {"query": "   "}, "Not_Found"),
    ("list_zotero_items", {"collection_key": "bad"}, "API_Error"),
    ("get_zotero_item", {"item_key": "bad"}, "API_Error"),
    ("zotero_api", {"method": "DELETE", "path": "items/ABCD1234"}, "API_Error"),
    ("zotero_api", {"method": "GET", "path": "keys/current"}, "API_Error"),
    # Some clients send an object argument as a JSON string.
    ("zotero_api", {"method": "DELETE", "path": "items", "query": '{"itemKey": "ABCD1234"}'}, "API_Error"),
    ("upload_zotero_file", {"item_key": "ABCD1234", "file_path": "no-such-file.pdf"}, "API_Error"),
    ("embed_zotero_word_fields", {"docx_path": "no-such-draft.docx"}, "API_Error"),
)


class _Server:
    """One `python -m zotero_mcp` process, started the way an MCP client starts it."""

    def __init__(self) -> None:
        # Dummy credentials win over any stored ones; no call below uses them.
        env = dict(os.environ, ZOTERO_USER_ID="1", ZOTERO_API_KEY="OfflineTestKey0123456789")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "zotero_mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.replies: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stray_output: list[bytes] = []
        self.log: list[bytes] = []
        self._next_id = 0
        self._readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for reader in self._readers:
            reader.start()

    def _read_stdout(self) -> None:
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                message = None
            if isinstance(message, dict) and message.get("jsonrpc") == "2.0":
                self.replies.put(message)
            else:
                self.stray_output.append(line)

    def _read_stderr(self) -> None:
        for line in self.process.stderr:
            self.log.append(line)

    def _send(self, message: dict[str, Any]) -> None:
        self.process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        while True:
            try:
                reply = self.replies.get(timeout=_TIMEOUT)
            except queue.Empty:
                log = b"".join(self.log[-20:]).decode("utf-8", "replace")
                raise AssertionError(f"No reply to {method}. Server log:\n{log}") from None
            if reply.get("id") == self._next_id:
                return reply

    def initialize(self, version: str) -> dict[str, Any]:
        reply = self.request(
            "initialize",
            {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "zotero-mcp-tests", "version": "1"}},
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply["result"]

    def close(self) -> int | None:
        """Close stdin, as a client does when it is done, and return the exit code."""
        self.process.stdin.close()
        try:
            return self.process.wait(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            return None
        finally:
            for reader in self._readers:
                reader.join(timeout=_TIMEOUT)
            self.process.stdout.close()
            self.process.stderr.close()


class ProtocolTests(unittest.TestCase):
    def test_every_protocol_version_negotiates(self) -> None:
        servers = {version: _Server() for version in (*_VERSIONS, "2099-01-01")}
        try:
            for version, server in servers.items():
                with self.subTest(version=version):
                    result = server.initialize(version)
                    expected = version if version in _VERSIONS else result["protocolVersion"]
                    self.assertIn(result["protocolVersion"], _VERSIONS)
                    self.assertEqual(result["protocolVersion"], expected)
                    self.assertEqual(result["serverInfo"]["name"], "zotero")
                    self.assertEqual(result["serverInfo"]["version"], __version__)
                    self.assertIn("tools", result["capabilities"])
                    self.assertIn("zotero_api", result["instructions"])
                    self.assertEqual(server.request("ping")["result"], {})
        finally:
            exit_codes = {version: server.close() for version, server in servers.items()}
        self.assertEqual(set(exit_codes.values()), {0}, exit_codes)

    def test_tools_work_over_stdio(self) -> None:
        server = _Server()
        try:
            server.initialize(_VERSIONS[-1])
            listed = server.request("tools/list")["result"]
            self.assertIsNone(listed.get("nextCursor"))
            tools = {tool["name"]: tool for tool in listed["tools"]}
            for name, tool in tools.items():
                with self.subTest(tool=name):
                    _check_definition(self, tool)
            for name, arguments, status in _OFFLINE_CALLS:
                with self.subTest(tool=name, arguments=arguments):
                    result = server.request("tools/call", {"name": name, "arguments": arguments})["result"]
                    _check_result(self, tools[name], result)
                    self.assertEqual(result["structuredContent"]["status"], status)
            rejected = server.request("tools/call", {"name": "search_zotero", "arguments": {"query": "x", "limit": 0}})
            self.assertTrue(rejected["result"]["isError"])
        finally:
            exit_code = server.close()
        self.assertEqual(exit_code, 0)
        self.assertEqual(server.stray_output, [], "only JSON-RPC messages may reach stdout")


def _check_definition(test: unittest.TestCase, tool: dict[str, Any]) -> None:
    """Hold a tool definition to what the strictest common clients accept."""
    test.assertRegex(tool["name"], _TOOL_NAME)
    test.assertTrue(tool.get("description", "").strip())
    test.assertTrue(tool.get("title"))
    test.assertIn("readOnlyHint", tool.get("annotations", {}))
    schema = tool["inputSchema"]
    test.assertEqual(schema["type"], "object")
    test.assertNotIn("$ref", json.dumps(schema), "some clients cannot resolve $ref in tool parameters")
    for name, prop in schema.get("properties", {}).items():
        test.assertTrue(prop.get("description"), f"{name} needs a description")
        test.assertTrue("type" in prop or "anyOf" in prop, f"{name} needs a type")
        for branch in [prop, *prop.get("anyOf", [])]:
            if branch.get("type") == "array":
                # Some clients rewrite untyped items, e.g. opencode declares them strings for Gemini models.
                test.assertIn("type", branch.get("items", {}), f"{name}: array parameters need typed items")
    test.assertEqual(tool["outputSchema"]["type"], "object")
    if Draft202012Validator is not None:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(tool["outputSchema"])


def _check_result(test: unittest.TestCase, tool: dict[str, Any], result: dict[str, Any]) -> None:
    """A result must suit clients that read structuredContent and clients that read only text."""
    test.assertFalse(result.get("isError"))
    structured = result["structuredContent"]
    test.assertEqual(result["content"][0]["type"], "text")
    test.assertEqual(json.loads(result["content"][0]["text"]), structured)
    if Draft202012Validator is not None:
        errors = [error.message for error in Draft202012Validator(tool["outputSchema"]).iter_errors(structured)]
        test.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
