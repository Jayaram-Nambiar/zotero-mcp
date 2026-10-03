# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-03

### Added

- Setup instructions for GitHub Copilot CLI, Gemini CLI, Cline, and Zed, and a table for Visual Studio, Devin, Kiro, JetBrains AI Assistant, Junie, Continue, goose, Warp, Qwen Code, Kilo Code, and Perplexity for Mac.
- `zotero_api` lists your group libraries with the path `groups`, and accepts numbers and true/false as query values, such as `{"limit": 10}`.
- A test suite that starts the server and talks to it the way agents do. It checks that every protocol version from 2024-11-05 to 2025-11-25 negotiates, that the tool definitions suit the strictest common clients, and that every result matches its declared schema.
- Continuous integration installs the package and runs the tests on Windows, macOS, and Linux with Python 3.10 and 3.14 for every push to `main` and every pull request.
- Every release has a Git tag, starting with `v1.0.0`, so a specific version can be installed and compared.

### Changed

- `embed_zotero_word_fields` asks zotero.org for up to 50 cited items in one request, instead of making two requests per item. When the desktop app does not answer, the server waits 30 seconds before asking it again. Long documents therefore convert well within the time agents allow for a tool call.
- `embed_zotero_word_fields` checks its arguments before it reads the library: the locale, the style, the paths, and the output folder.
- In a citation marker with several items, `prefix` now goes before the first item and `suppress-author` applies to every item. `locator` and `suffix` stay on the last item.
- The read tools, `upload_zotero_file`, and `embed_zotero_word_fields` are marked as closed-world tools, so VS Code no longer holds their results for approval. `upload_zotero_file` is marked as non-destructive and safe to repeat.
- Parameter descriptions state their defaults and ranges, for agents that drop those parts of a tool's schema. `zotero_api`'s `body` is an object or an array of objects.
- A web request now gives up after 30 seconds instead of 60, so the agent receives the server's error before the agent's own time limit.
- File paths must be full paths. A path that starts with `~` means your home folder.
- The README is a step-by-step guide for beginners. It covers:
  - prerequisites and Zotero setup;
  - storing the API key without showing it on screen or saving it in shell history;
  - installing Git and uv;
  - connecting each agent, with commands to open and check its config file;
  - Word citations, including what a paragraph with a marker loses;
  - updating, pinning, and removing the server;
  - troubleshooting, with where each agent shows the connection and its logs.
- The README says to quit Claude Desktop completely before you edit its config file, gives the current Windows location of its log, and explains the environment editor of the desktop app's Code tab. It adds the VS Code trust prompt, Codex's startup wait, opencode's timeout, and the current Antigravity menus.
- `CONTRIBUTING.md` documents development setup, project rules, commit messages, pull requests, and the release process. `SECURITY.md` documents supported versions, how to report a vulnerability, and the server's safeguards.
- The package declares its license as an SPDX expression, which setuptools requires from 2027, and caps `pydantic` and `python-docx` below their next major versions.

### Fixed

- Tools return an `API_Error` that explains the problem, instead of a bare "Error executing tool", when a connection drops, a response is cut off, a file cannot be read, or a document is not a readable `.docx` file.
- A 404 answer from the desktop app's local API no longer stops reads from falling back to zotero.org.
- Cases, statutes, and emails appear in search and item results, with their dates and publications. Items without a title are listed instead of dropped.
- A write that Zotero rejects in part reports how many objects failed instead of a plain `OK`. A write it rejects entirely is an `API_Error`.
- `list_zotero_collections` returns every collection instead of stopping at 1,100.
- `embed_zotero_word_fields` never writes over the original document. It no longer adds empty header and footer parts, numbers the placeholder bibliography correctly, names the marker or item key that stopped a conversion, removes its temporary files after a failure, and accepts `https://` style links.
- `LOG_LEVEL` takes effect, in any letter case.
- On Windows, a value that is not a user ID or key, such as a reference the agent did not expand like `${env:ZOTERO_API_KEY}`, falls back to the stored variable.

### Security

- The API key is no longer sent along when Zotero redirects a request to another host, such as its file storage.
- A user ID or key with unexpected characters, such as a line break, is treated as missing, so it cannot appear in an error message.

## [1.0.2] - 2026-10-02

### Added

- On Windows, the server reads `ZOTERO_USER_ID` and `ZOTERO_API_KEY` from your user or system environment variables when the agent does not pass them, or passes an empty value or the `YOUR_` placeholder. Claude Desktop, which passes no user variables to servers, and Microsoft Store apps started before the variables were set now work without an `env` block or a restart. A value the agent passes still takes precedence.

### Changed

- The README installs the server with uv or pipx and points every agent at the full path of the `zotero-mcp` command. It adds opencode, covers updating and removing the server, and no longer tells Windows users to paste the API key into Claude Desktop and Antigravity configs.

## [1.0.1] - 2026-10-02

### Fixed

- `embed_zotero_word_fields` no longer fails with `No Zotero item was loaded for …` on documents with more than a few citation markers. The pass that collects item keys skipped marker paragraphs, so their items were never fetched.

## [1.0.0] - 2026-10-02

### Added

- First public release.
- Search, list, and fetch items from the local Zotero app or api.zotero.org.
- Call the Zotero Web API, including guarded deletes and attachment upload.
- Write Microsoft Word citation and bibliography fields, plus `ZOTERO_PREF_*` document preferences, so the Zotero Word plugin can refresh them.

[Unreleased]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Jayaram-Nambiar/zotero-mcp/tree/v1.0.0
