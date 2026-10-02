# Changelog

## 1.0.2

- On Windows, the server reads `ZOTERO_USER_ID` and `ZOTERO_API_KEY` from your user or system environment variables when the agent does not pass them, or passes an empty value or the `YOUR_` placeholder. Claude Desktop, which passes no user variables to servers, and Microsoft Store apps started before the variables were set now work without an `env` block or a restart. A value the agent passes still takes precedence.
- The README installs the server with uv or pipx and points every agent at the full path of the `zotero-mcp` command. It adds opencode, covers updating and removing the server, and drops instructions that pasted the API key into Claude Desktop and Antigravity configs on Windows.

## 1.0.1

- `embed_zotero_word_fields` no longer fails with `No Zotero item was loaded for …` on documents with more than a few citation markers. The pass that collects item keys skipped marker paragraphs, so their items were never fetched.

## 1.0.0

First public release.

- Search, list, and fetch items from the local Zotero app or api.zotero.org.
- Call the Zotero Web API, including guarded deletes and attachment upload.
- Write Microsoft Word citation and bibliography fields, plus `ZOTERO_PREF_*` document preferences, so the Zotero Word plugin can refresh them.
