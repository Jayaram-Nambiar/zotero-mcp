# Contributing

Thank you for helping improve zotero-mcp. The project is deliberately small, so that a person or an AI agent can change it safely. This guide covers how to report problems, set up a development environment, follow the project's rules, and publish a release.

## Report a bug or suggest a change

[Open an issue](https://github.com/Jayaram-Nambiar/zotero-mcp/issues) and include:

- your operating system and the agent you use;
- the installed version, from `uv tool list`;
- what you did, what you expected, and what happened, with the exact error message.

Never include your API key, and write `YOUR_USER_ID` in place of your Zotero user ID. To report a security problem, follow [SECURITY.md](SECURITY.md) instead.

## Set up a development environment

You need Git and Python 3.10 or newer.

1. Clone the repository and enter it:

   ```bash
   git clone https://github.com/Jayaram-Nambiar/zotero-mcp.git
   cd zotero-mcp
   ```

2. Create a virtual environment and install the package in editable mode, so that the tests import your working copy.

   Windows (PowerShell):

   ```powershell
   python -m venv .venv
   .venv/Scripts/python -m pip install -e .
   ```

   macOS and Linux:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

Use this interpreter for every command below: `.venv/Scripts/python` on Windows, `.venv/bin/python` on macOS and Linux. Another interpreter fails with `ModuleNotFoundError: No module named 'zotero_mcp'`.

Agents keep running the copy installed with `uv tool install` (see the [README](README.md#step-3-install-zotero-mcp)), not this checkout. Your changes reach them only after they are pushed to `main` and the installed copy is updated with `uv tool upgrade zotero-mcp`, which installs the newest commit on `main`.

## Run the tests

The tests run offline and never contact Zotero. They take about 20 seconds:

| File | What it covers |
| --- | --- |
| `tests/test_client.py` | Credentials, path rules, item fields, tool names and annotations |
| `tests/test_http.py` | Requests against fake Zotero servers on `127.0.0.1`: network failures, the desktop-app fallback, redirects, writes, uploads, and batched reads |
| `tests/test_word.py` | The Word field writer and `embed_zotero_word_fields`, with `.docx` files built in a temporary folder |
| `tests/test_protocol.py` | The server started the way agents start it, over standard input and output: every protocol version, the tool definitions, and each result against its declared schema |

Windows (PowerShell):

```powershell
.venv/Scripts/python -m unittest discover -s tests
```

macOS and Linux:

```bash
.venv/bin/python -m unittest discover -s tests
```

To run one test, or only the tests whose names contain a word, pass its name or `-k`. Windows is shown; on macOS and Linux, use `.venv/bin/python`:

```powershell
.venv/Scripts/python -m unittest tests.test_word.WordFieldTests.test_marker_options
.venv/Scripts/python -m unittest discover -s tests -k marker
```

[GitHub Actions](.github/workflows/tests.yml) installs the package and runs the same suite on Windows, macOS, and Linux, with Python 3.10 and 3.14, for every push to `main` and every pull request.

## Rules for every change

1. **Run the tests before you commit.** CI must pass before a change is merged.
2. **Write for Python 3.10.** It is the oldest supported version, and newer syntax or standard-library calls fail there.
3. **Keep tool names aligned with what they do.** `search_zotero` searches; `embed_zotero_word_fields` writes Word fields. A rename is a breaking change and needs a `CHANGELOG.md` entry. What an agent reads about a tool lives in four places that change together: the `instructions` string in `src/zotero_mcp/server.py`, the tool's docstring, its `Field(description=...)` annotations, and the tool table in the README.
4. **Keep tool definitions portable.** Agents pass tool definitions to different model providers, and some rewrite them. Tool names match `^[A-Za-z0-9_-]{1,64}$`; input schemas use no `$ref`; array parameters have typed items; and descriptions state defaults and ranges, because some agents drop `default`, `minimum`, and `maximum`. Annotations stay accurate: `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`, which VS Code uses to decide what the user approves. `tests/test_protocol.py` checks the definitions.
5. **Errors are data.** A tool returns its result model with a `status` and a clear `message`; it never raises to the agent. A new read path catches `READ_ERRORS` from `src/zotero_mcp/client.py`, and a new failure type is mapped there or turned into an `API_Error` result.
6. **Treat the Word field text as a compatibility contract.** `tests/test_word.py` checks the `ADDIN ZOTERO_ITEM CSL_CITATION` and `ADDIN ZOTERO_BIBL` instructions and the `ZOTERO_PREF_*` properties. Change the writer and those tests in the same commit.
7. **Keep Zotero's source code out.** Zotero is licensed under the GNU AGPL. This project is MIT-licensed and implements the documented field format itself.
8. **Keep secrets and private data out.** Do not commit API keys, user IDs, `.env` files, or documents from a real library. Tests must not read real credentials either. On Windows the server falls back to the stored user environment, so a test that reaches credential code replaces `zotero_mcp.client._windows_environment` with a fake (see `_credentials()` in `tests/test_client.py`). Fake credentials must look real: digits for the user ID, and letters and digits for the key. The server treats anything else as unset and would fall back to the stored values.
9. **Never write to standard output in the server.** Standard output carries the MCP protocol. Log with `logging`, which writes to standard error.
10. **Update the documentation in the same change.** A change that affects setup or behavior updates the README, and every change users notice gets an entry under `[Unreleased]` in `CHANGELOG.md`. Check every statement about an agent's configuration against that agent's current documentation.

## Commit messages

- Write the subject as one sentence in the imperative mood, starting with a capital letter and ending with a period, for example: `Fix Word embedding failing on documents with many citation markers.`
- Use the body to explain why the change is needed and what it changes.
- Keep each commit to one logical change.

## Pull requests

1. Fork the repository on GitHub and clone your fork. Maintainers can work in the repository directly.
2. Create a branch from `main`.
3. Make the change, together with its tests and documentation.
4. Run the test suite.
5. Push the branch and open a pull request that explains the problem and the change. CI runs automatically and must pass before the change is merged.

## Release a new version

Maintainers publish releases. Versions follow [Semantic Versioning](https://semver.org/): a patch release for fixes, a minor release for new features, and a major release for breaking changes.

1. In `CHANGELOG.md`, rename `[Unreleased]` to the new version and today's date, add a new empty `[Unreleased]` section above it, and update the comparison links at the bottom of the file.
2. Set the new version in all three places: `version` in `pyproject.toml`, `__version__` in `src/zotero_mcp/__init__.py`, and `version` and `date-released` in `CITATION.cff`.
3. Run the test suite.
4. Commit the release:

   ```bash
   git commit -am "Release X.Y.Z."
   ```

5. Push the commit:

   ```bash
   git push origin main
   ```

6. Wait until the **Tests** workflow passes for that commit, on the repository's **Actions** tab.
7. Tag the release and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "zotero-mcp X.Y.Z"
   git push origin vX.Y.Z
   ```

8. Update your own installation with `uv tool upgrade zotero-mcp`, then restart your agents.
