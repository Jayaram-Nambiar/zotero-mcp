"""Tests that do not call Zotero."""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

from zotero_mcp import client
from zotero_mcp.client import api_target, csl_item, plain_text, redact, require_user_id, web_credentials
from zotero_mcp.models import UnconfiguredError
from zotero_mcp.server import mcp, search_zotero, zotero_api

_NAMES = ("ZOTERO_USER_ID", "ZOTERO_API_KEY")


@contextmanager
def _credentials(passed: dict[str, str], stored: dict[str, str]):
    """Run with only `passed` in os.environ and `stored` as the Windows environment."""
    previous = {name: os.environ.pop(name, None) for name in _NAMES}
    os.environ.update(passed)
    try:
        with mock.patch.object(client, "_windows_environment", side_effect=lambda name: stored.get(name, "")):
            yield
    finally:
        for name, value in previous.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


class ClientTests(unittest.TestCase):
    def test_api_target_refuses_urls_and_keys(self) -> None:
        with self.assertRaises(ValueError):
            api_target("https://api.zotero.org/users/1/items", "1")
        with self.assertRaises(ValueError):
            api_target("keys/current", "1")
        self.assertEqual(api_target("items/ABCD1234", "42"), "users/42/items/ABCD1234")
        self.assertEqual(api_target("groups/7/items", "42"), "groups/7/items")

    def test_redact_removes_secret(self) -> None:
        self.assertEqual(redact("token secret token", "secret"), "token [redacted] token")

    def test_placeholder_credentials_are_ignored(self) -> None:
        with _credentials({"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "YOUR_API_KEY"}, {}):
            self.assertIsNone(web_credentials())

    def test_windows_environment_fills_what_the_agent_did_not_pass(self) -> None:
        stored = {"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "stored-key"}
        for passed in (
            {},
            {"ZOTERO_USER_ID": "", "ZOTERO_API_KEY": ""},
            {"ZOTERO_USER_ID": "YOUR_USER_ID", "ZOTERO_API_KEY": "YOUR_API_KEY"},
        ):
            with self.subTest(passed=passed), _credentials(passed, stored):
                self.assertEqual(web_credentials(), ("42", "stored-key"))
                self.assertEqual(require_user_id(), "42")

    def test_agent_values_win_over_the_windows_environment(self) -> None:
        passed = {"ZOTERO_USER_ID": "7", "ZOTERO_API_KEY": "agent-key"}
        with _credentials(passed, {"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "stored-key"}):
            self.assertEqual(web_credentials(), ("7", "agent-key"))
            self.assertEqual(require_user_id(), "7")

    def test_credentials_missing_everywhere_are_unconfigured(self) -> None:
        with _credentials({}, {"ZOTERO_API_KEY": "YOUR_API_KEY"}):
            self.assertIsNone(web_credentials())
            with self.assertRaises(UnconfiguredError):
                require_user_id()

    @unittest.skipUnless(sys.platform == "win32", "reads the Windows registry")
    def test_windows_environment_reads_user_then_system_variables(self) -> None:
        temp = client._windows_environment("TEMP")
        self.assertNotIn("%", temp)
        self.assertTrue(temp.lower().startswith(os.path.expanduser("~").lower()))
        self.assertEqual(client._windows_environment("OS"), "Windows_NT")
        self.assertEqual(client._windows_environment("ZOTERO_MCP_TEST_NEVER_SET"), "")

    def test_windows_environment_is_empty_on_other_systems(self) -> None:
        with mock.patch.object(client.sys, "platform", "linux"):
            self.assertEqual(client._windows_environment("TEMP"), "")

    def test_csl_item_accepts_export_shapes(self) -> None:
        item = {"type": "article-journal", "title": "Example"}
        self.assertEqual(csl_item([item]), item)
        self.assertEqual(csl_item(item), item)

    def test_plain_text_strips_markup(self) -> None:
        self.assertEqual(plain_text("<div>Smith &amp; Jones</div>"), "Smith & Jones")

    def test_delete_requires_confirmation(self) -> None:
        result = zotero_api("DELETE", "items/ABCD1234", confirm_delete=False)
        self.assertEqual(result.status, "API_Error")
        self.assertIn("confirm_delete", result.message)

    def test_empty_search_does_not_call_the_network(self) -> None:
        result = search_zotero("  ")
        self.assertEqual(result.status, "Not_Found")

    def test_tool_names_match_their_jobs(self) -> None:
        names = set(mcp._tool_manager._tools)
        self.assertEqual(
            names,
            {
                "search_zotero",
                "list_zotero_items",
                "list_zotero_collections",
                "get_zotero_item",
                "zotero_api",
                "upload_zotero_file",
                "embed_zotero_word_fields",
            },
        )


if __name__ == "__main__":
    unittest.main()
