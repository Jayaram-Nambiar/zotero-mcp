# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Continuous integration installs the package and runs the test suite on Windows, macOS, and Linux with Python 3.10 and 3.14 for every push to `main` and every pull request.
- Every release has a Git tag (`v1.0.0`, `v1.0.1`, `v1.0.2`), so a specific version can be installed and compared.

### Changed

- The README is now a step-by-step guide for beginners. It covers:
  - prerequisites and Zotero setup;
  - storing the API key without showing it on screen or saving it in shell history;
  - installing Git and uv;
  - connecting each agent, with commands to open and check its config file;
  - Word citations, including what a paragraph with a marker loses;
  - updating, pinning, and removing the server;
  - expanded troubleshooting with log locations.
- The Claude Desktop instructions say to quit the app completely, from the notification area or menu bar, before editing its config file, because a running app can save its own copy of the file over the change.
- The README again lists the ChatGPT desktop app among the apps that share `~/.codex/config.toml`, as OpenAI's MCP guide states.
- `CONTRIBUTING.md` documents development setup, project rules, commit messages, pull requests, and the release process. `SECURITY.md` documents supported versions, how to report a vulnerability, and the server's safeguards.

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

[Unreleased]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Jayaram-Nambiar/zotero-mcp/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Jayaram-Nambiar/zotero-mcp/tree/v1.0.0
