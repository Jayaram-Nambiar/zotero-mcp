"""Tests that do not call Zotero."""

from __future__ import annotations

import logging
import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

from zotero_mcp import client
from zotero_mcp.__main__ import log_level
from zotero_mcp.client import api_target, csl_item, item_summary, plain_text, redact, require_user_id, web_credentials
from zotero_mcp.models import UnconfiguredError
from zotero_mcp.server import mcp, search_zotero, zotero_api

_NAMES = ("ZOTERO_USER_ID", "ZOTERO_API_KEY")
_STORED = {"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "StoredKey0123456789abcde"}


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


def _record(**data: str) -> dict:
    return {"key": "ABCD1234", "data": data}


class ClientTests(unittest.TestCase):
    def test_api_target_refuses_urls_and_keys(self) -> None:
        with self.assertRaises(ValueError):
            api_target("https://api.zotero.org/users/1/items", "1")
        with self.assertRaises(ValueError):
            api_target("keys/current", "1")
        self.assertEqual(api_target("items/ABCD1234", "42"), "users/42/items/ABCD1234")
        self.assertEqual(api_target("groups/7/items", "42"), "groups/7/items")

    def test_bare_groups_lists_the_users_groups(self) -> None:
        self.assertEqual(api_target("groups", "42"), "users/42/groups")

    def test_redact_removes_secret(self) -> None:
        self.assertEqual(redact("token secret token", "secret"), "token [redacted] token")

    def test_placeholder_credentials_are_ignored(self) -> None:
        with _credentials({"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "YOUR_API_KEY"}, {}):
            self.assertIsNone(web_credentials())

    def test_windows_environment_fills_what_the_agent_did_not_pass(self) -> None:
        for passed in (
            {},
            {"ZOTERO_USER_ID": "", "ZOTERO_API_KEY": ""},
            {"ZOTERO_USER_ID": "YOUR_USER_ID", "ZOTERO_API_KEY": "YOUR_API_KEY"},
        ):
            with self.subTest(passed=passed), _credentials(passed, _STORED):
                self.assertEqual(web_credentials(), ("42", _STORED["ZOTERO_API_KEY"]))
                self.assertEqual(require_user_id(), "42")

    def test_references_an_agent_did_not_expand_count_as_unset(self) -> None:
        for reference in ("${env:ZOTERO_API_KEY}", "$ZOTERO_API_KEY", "{env:ZOTERO_API_KEY}", "%ZOTERO_API_KEY%"):
            with self.subTest(reference=reference), _credentials({"ZOTERO_API_KEY": reference}, _STORED):
                self.assertEqual(web_credentials(), ("42", _STORED["ZOTERO_API_KEY"]))

    def test_agent_values_win_over_the_windows_environment(self) -> None:
        passed = {"ZOTERO_USER_ID": "7", "ZOTERO_API_KEY": "AgentKey0123456789abcdef"}
        with _credentials(passed, _STORED):
            self.assertEqual(web_credentials(), ("7", "AgentKey0123456789abcdef"))
            self.assertEqual(require_user_id(), "7")

    def test_credentials_missing_everywhere_are_unconfigured(self) -> None:
        with _credentials({}, {"ZOTERO_API_KEY": "YOUR_API_KEY"}):
            self.assertIsNone(web_credentials())
            with self.assertRaises(UnconfiguredError):
                require_user_id()

    def test_malformed_credentials_are_unconfigured(self) -> None:
        # A line break in a header value would make http.client echo the key in an error.
        for passed in (
            {"ZOTERO_USER_ID": "42", "ZOTERO_API_KEY": "Secret\nPart"},
            {"ZOTERO_USER_ID": "４２", "ZOTERO_API_KEY": "AgentKey0123456789abcdef"},
        ):
            with self.subTest(passed=passed), _credentials(passed, {}):
                self.assertIsNone(web_credentials())

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

    def test_item_types_with_their_own_title_fields_are_listed(self) -> None:
        case = item_summary(_record(itemType="case", caseName="Roe v. Wade", dateDecided="1973"))
        statute = item_summary(_record(itemType="statute", nameOfAct="Data Act", dateEnacted="2018"))
        email = item_summary(_record(itemType="email", subject="Draft"))
        webpage = item_summary(_record(itemType="webpage", title="Docs", websiteTitle="Zotero"))
        untitled = item_summary(_record(itemType="journalArticle", publicationTitle="Nature"))
        self.assertEqual((case.title, case.date), ("Roe v. Wade", "1973"))
        self.assertEqual((statute.title, statute.date), ("Data Act", "2018"))
        self.assertEqual(email.title, "Draft")
        self.assertEqual(webpage.publication, "Zotero")
        self.assertEqual((untitled.title, untitled.publication), ("", "Nature"))
        self.assertIsNone(item_summary(_record(itemType="note", note="<p>text</p>")))

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

    def test_query_values_accept_numbers_and_booleans(self) -> None:
        with mock.patch("zotero_mcp.server.web_send") as send:
            zotero_api("GET", "items", query={"limit": 5, "includeTrashed": True, "q": "x", "start": 0.0})
        self.assertEqual(send.call_args.kwargs["query"], {"limit": "5", "includeTrashed": "1", "q": "x", "start": "0.0"})
        refused = zotero_api("GET", "items", query={"itemKey": ["ABCD1234"]})
        self.assertEqual(refused.status, "API_Error")
        self.assertIn("commas", refused.message)

    def test_empty_search_does_not_call_the_network(self) -> None:
        result = search_zotero("  ")
        self.assertEqual(result.status, "Not_Found")

    def test_log_level_accepts_any_letter_case(self) -> None:
        self.assertEqual(log_level("debug"), logging.DEBUG)
        self.assertEqual(log_level(" Warning "), logging.WARNING)
        self.assertEqual(log_level(None), logging.INFO)
        self.assertEqual(log_level("verbose"), logging.INFO)

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

    def test_tool_annotations_describe_what_each_tool_changes(self) -> None:
        tools = mcp._tool_manager._tools
        for name in ("search_zotero", "list_zotero_items", "list_zotero_collections", "get_zotero_item"):
            self.assertTrue(tools[name].annotations.read_only_hint, name)
        # Only zotero_api reaches beyond the user's library; VS Code holds open-world results for approval.
        self.assertEqual({name for name, tool in tools.items() if tool.annotations.open_world_hint}, {"zotero_api"})
        self.assertTrue(tools["zotero_api"].annotations.destructive_hint)
        self.assertFalse(tools["upload_zotero_file"].annotations.destructive_hint)
        self.assertTrue(tools["upload_zotero_file"].annotations.idempotent_hint)
        self.assertTrue(tools["embed_zotero_word_fields"].annotations.idempotent_hint)


if __name__ == "__main__":
    unittest.main()
