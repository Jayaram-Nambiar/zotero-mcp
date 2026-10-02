"""Tests that do not call Zotero."""

from __future__ import annotations

import os
import unittest

from zotero_mcp.client import api_target, csl_item, plain_text, redact, web_credentials
from zotero_mcp.server import mcp, search_zotero, zotero_api


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
        previous = {name: os.environ.get(name) for name in ("ZOTERO_USER_ID", "ZOTERO_API_KEY")}
        os.environ["ZOTERO_USER_ID"] = "42"
        os.environ["ZOTERO_API_KEY"] = "YOUR_API_KEY"
        try:
            self.assertIsNone(web_credentials())
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

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
