# zotero-mcp

A [Model Context Protocol](https://modelcontextprotocol.io/) server for one person's Zotero library. It can search the library, call the [Zotero Web API v3](https://www.zotero.org/support/dev/web_api/v3/basics), upload attachment files, and write Microsoft Word fields that the [Zotero Word plugin](https://www.zotero.org/support/word_processor_plugin_usage) can refresh and restyle.

Set it up once for every agent you use: install the `zotero-mcp` command, store your Zotero user ID and API key as user environment variables, and point each agent at that command. Agents start the server themselves and talk to it over standard input and output, so there is nothing to keep running in a terminal.

## What you need

- Windows, macOS, or Linux, with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/) to install the server. The server needs Python 3.10 or newer; uv downloads one if none is installed.
- The [Zotero desktop app](https://www.zotero.org/download/), for fast local reads.
- A [zotero.org](https://www.zotero.org/user/register) account, its numeric user ID, and an API key.
- For Word citations: Microsoft Word and the [Zotero word-processor plugin](https://www.zotero.org/support/word_processor_plugin_installation).

Reads try the desktop app at `http://127.0.0.1:23119/api` first. Zotero documents that local API as `localhost` port `23119`; this server uses `127.0.0.1` so an IPv6 localhost lookup does not stall. If the app is closed, or its library has no items yet, reads use `https://api.zotero.org`. Writes always use `api.zotero.org`, and Zotero syncs them back to the desktop app.

## 1. Set up Zotero

1. Install Zotero from the [download page](https://www.zotero.org/download/) and open it once.
2. Create an account from [zotero.org/user/register](https://www.zotero.org/user/register) if you do not have one.
3. In Zotero, sign in and let the library sync. Then open Settings and turn on the option that allows other applications on this computer to communicate with Zotero. Zotero describes this local API in the [Web API basics](https://www.zotero.org/support/dev/web_api/v3/basics).
4. While logged in on the web, open [API key settings](https://www.zotero.org/settings/keys).
5. Create a private key for this server. Give it access to your personal library. Turn on write access only if agents should be allowed to create, edit, upload, or delete records. The page shows the key once. Copy it then.
6. On that same page, copy your **user ID**. It is a number. It is not your username.

The user ID is required for Word. The plugin matches a citation to your library with a URI of the form `http://zotero.org/users/USERID/items/ITEMKEY`.

To install the Word plugin, follow [Installing the Zotero word-processor plugin](https://www.zotero.org/support/word_processor_plugin_installation): in Zotero, open the Cite settings, install the Microsoft Word add-in, and restart Word. A Zotero tab should appear. [Using the plugin](https://www.zotero.org/support/word_processor_plugin_usage) explains Add/Edit Citation, Add/Edit Bibliography, Document Preferences, and Refresh.

## 2. Store the user ID and API key

Store both values once, as user environment variables. Every agent can then reach them, and neither value has to be written into an agent's config file. Do not commit either value. [`.env.example`](.env.example) lists the names; the server does not load `.env` files.

Windows PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("ZOTERO_USER_ID", "YOUR_USER_ID", "User")
[Environment]::SetEnvironmentVariable("ZOTERO_API_KEY", "YOUR_API_KEY", "User")
```

On Windows the server reads these variables itself whenever an agent does not pass them, so they take effect on the next request in every agent, with nothing to restart. That covers agents that withhold your variables from the servers they start, such as Claude Desktop, and Microsoft Store apps that still carry the environment from when you signed in.

macOS and Linux, in `~/.zshrc` or `~/.bashrc`:

```bash
export ZOTERO_USER_ID="YOUR_USER_ID"
export ZOTERO_API_KEY="YOUR_API_KEY"
```

Agents started from a new terminal inherit these. Apps opened from the Dock or an application menu do not read shell profiles; for those, put the values in the agent's `env` block in step 4.

## 3. Install

Install the server in its own environment, so that changes to other Python tools cannot break it:

```bash
uv tool install "git+https://github.com/Jayaram-Nambiar/zotero-mcp.git"
```

With pipx instead: `pipx install "git+https://github.com/Jayaram-Nambiar/zotero-mcp.git"`.

Either one installs a `zotero-mcp` command. `uv tool list` (or `pipx list`) shows the installed version. Agents need the command's full path:

| System | Full path |
| --- | --- |
| Windows | `%USERPROFILE%\.local\bin\zotero-mcp.exe`. `uv tool dir --bin` prints the folder. |
| macOS, Linux | `~/.local/bin/zotero-mcp`. `uv tool dir --bin` prints the folder. |

pipx uses the same folder by default; `pipx environment` shows it as `PIPX_BIN_DIR`.

## 4. Connect your agents

Add the server to each agent under the same name, `zotero`. The examples write the command as `zotero-mcp`. Replace it with the full path from step 3, because desktop apps do not always start with the `PATH` your terminal has:

- JSON on Windows doubles each backslash: `"C:\\Users\\you\\.local\\bin\\zotero-mcp.exe"`.
- TOML on Windows takes a literal string in single quotes: `'C:\Users\you\.local\bin\zotero-mcp.exe'`.
- macOS and Linux: `"/Users/you/.local/bin/zotero-mcp"` or `"/home/you/.local/bin/zotero-mcp"`.

After saving a config, reload the agent's MCP servers or restart the agent. The first successful `search_zotero` call confirms the setup.

### Claude Code

```bash
claude mcp add --scope user --transport stdio zotero -- zotero-mcp
```

User scope makes the server available in every project, and `claude mcp get zotero` shows its status. Claude Code passes its environment to the server. Claude Code documents scopes in [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp).

### Claude Desktop

Open **Settings → Developer → Edit Config**, or edit the file directly:

| System | File |
| --- | --- |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "zotero": {
      "command": "zotero-mcp"
    }
  }
}
```

Claude Desktop starts servers with system variables only, so it never passes yours. On Windows nothing more is needed, because the server reads the two variables itself. On macOS, add them to the entry and keep the file private:

```json
"env": {
  "ZOTERO_USER_ID": "YOUR_USER_ID",
  "ZOTERO_API_KEY": "YOUR_API_KEY"
}
```

### Cursor

`~/.cursor/mcp.json` (`%USERPROFILE%\.cursor\mcp.json` on Windows) applies to every project; `.cursor/mcp.json` inside a project applies to that project only. Cursor documents both in [Model Context Protocol](https://cursor.com/docs/mcp).

```json
{
  "mcpServers": {
    "zotero": {
      "type": "stdio",
      "command": "zotero-mcp",
      "env": {
        "ZOTERO_USER_ID": "${env:ZOTERO_USER_ID}",
        "ZOTERO_API_KEY": "${env:ZOTERO_API_KEY}"
      }
    }
  }
}
```

`${env:NAME}` copies each variable from Cursor's environment when the server starts, so the key is not stored in the file.

### VS Code with GitHub Copilot

Run **MCP: Open User Configuration** to add the server for every workspace, or use `.vscode/mcp.json` for one workspace. VS Code uses `servers`, not `mcpServers`; the [MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) describes the format.

```json
{
  "servers": {
    "zotero": {
      "type": "stdio",
      "command": "zotero-mcp"
    }
  }
}
```

On macOS and Linux, start VS Code from a terminal that has the variables, or add an `env` object with the values and keep that file out of version control.

### Codex

The Codex app, CLI, and IDE extension read `~/.codex/config.toml` (`%USERPROFILE%\.codex\config.toml` on Windows). OpenAI documents the keys in the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

```toml
[mcp_servers.zotero]
command = "zotero-mcp"
env_vars = ["ZOTERO_USER_ID", "ZOTERO_API_KEY"]
startup_timeout_sec = 30
```

`env_vars` forwards the two variables from Codex's environment, so the key stays out of the file. From the CLI: `codex mcp add zotero -- zotero-mcp`. ChatGPT in a web browser cannot start a program on your computer.

### Google Antigravity

The global file is `~/.gemini/config/mcp_config.json` (`%USERPROFILE%\.gemini\config\mcp_config.json` on Windows). In the app, **Additional Options (…) → MCP Servers** lists the connected servers and their tools. Antigravity documents the format in [its MCP guide](https://antigravity.google/docs/mcp/).

```json
{
  "mcpServers": {
    "zotero": {
      "command": "zotero-mcp"
    }
  }
}
```

Antigravity passes its environment to the server, so no `env` block is needed when it starts with the variables. Its config does not expand variable references; if Antigravity starts without the variables, as a macOS app opened from the Dock does, add an `env` object with the values.

### opencode

`~/.config/opencode/opencode.json`, or `opencode.jsonc` in the same folder. opencode documents local servers in [MCP servers](https://opencode.ai/docs/mcp-servers/).

```json
{
  "mcp": {
    "zotero": {
      "type": "local",
      "command": ["zotero-mcp"],
      "enabled": true,
      "environment": {
        "ZOTERO_USER_ID": "{env:ZOTERO_USER_ID}",
        "ZOTERO_API_KEY": "{env:ZOTERO_API_KEY}"
      }
    }
  }
}
```

opencode replaces `{env:NAME}` with the variable's value when it loads the file.

### Other MCP clients

A client that can start a local server needs:

| Setting | Value |
| --- | --- |
| Transport | stdio |
| Command | The full path of `zotero-mcp` from step 3 |
| Arguments | None |
| Environment | `ZOTERO_USER_ID` and `ZOTERO_API_KEY`; optional on Windows |

The server does not open a network port. Perplexity's MCP documentation covers connecting other clients *to* Perplexity ([MCP server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server)), not starting a local server from the Perplexity app.

## 5. Use the tools

| Tool | What it does |
| --- | --- |
| `search_zotero` | Search title, creator, or year. The `query` argument is one Zotero quick-search phrase. |
| `list_zotero_items` | Page through the library, or one collection when `collection_key` is set. |
| `list_zotero_collections` | List collections. |
| `get_zotero_item` | Fetch one item, including its abstract and a Vancouver line. |
| `zotero_api` | Send any other Web API v3 request. `DELETE` requires `confirm_delete` true. |
| `upload_zotero_file` | Upload a file onto an attachment item that already exists. |
| `embed_zotero_word_fields` | Replace citation markers in a `.docx` with Zotero Word fields. |

Search results are one page. Call again with `start` set to the returned `next_start` until `next_start` is null. Item keys are eight letters or digits. Write requests are documented in [Write Requests](https://www.zotero.org/support/dev/web_api/v3/write_requests) and [File Uploads](https://www.zotero.org/support/dev/web_api/v3/file_upload).

The tools are also plain Python functions. In an environment where the package is installed (see [Development](#development)):

```python
from zotero_mcp.server import embed_zotero_word_fields, search_zotero

page = search_zotero("vaswani attention")
print(page.matches[0].item_key)
print(embed_zotero_word_fields(r"C:\drafts\paper.docx"))
```

## 6. Word citations the plugin can edit

Plain text such as `(Smith, 2020)` or a pasted Vancouver line is not a Zotero citation. The plugin reads a Word field. Zotero explains that storage in [Why do I see ADDIN ZOTERO_ITEM CSL_CITATION?](https://www.zotero.org/support/kb/word_field_codes).

Put markers in the document while it is being written:

```text
{{zotero:ABCD1234}}
{{zotero:ABCD1234+EFGH5678}}
{{zotero:ABCD1234|locator=12|label=page}}
{{zotero:ABCD1234|prefix=see|suffix=.}}
{{zotero:bibliography}}
```

`ABCD1234` is the item key from `search_zotero`. A plus sign joins items into one citation cluster. `label` defaults to `page`. A suffix is appended as written. `{{zotero:bibliography}}` is the reference list.

Optional `suppress-author` is `true` or `false`. Locator labels follow CSL: `page`, `chapter`, `figure`, `paragraph`, `volume`, and the other terms accepted by the tool. Spaces around the marker are allowed. The word `zotero` stays lowercase.

Then ask the agent to call `embed_zotero_word_fields`, or run:

```python
from docx import Document
from zotero_mcp.server import embed_zotero_word_fields

document = Document()
document.add_paragraph("Attention is all you need {{zotero:ABCD1234}}.")
document.add_paragraph("{{zotero:bibliography}}")
document.save("draft.docx")

print(embed_zotero_word_fields("draft.docx", style="vancouver"))
```

The default output is `draft.zotero.docx` next to the original. The original is left in place. `style` is a [Zotero style name](https://www.zotero.org/styles) such as `vancouver` or `apa`, or a full `https://www.zotero.org/styles/...` URL. `locale` defaults to `en-US`.

Open the new file in Word and choose **Zotero → Refresh**. Document Preferences can change the citation style after that. The numbers you see before Refresh are a readable stand-in; Refresh rewrites them from the style.

The writer covers body paragraphs, table cells, and each section's main header and footer. It does not scan footnotes, text boxes, or first-page and even-page headers. A paragraph that contains a marker is rewritten as ordinary runs plus fields, so mixed bold or italic in that paragraph is not kept. The fields are in-text Word fields. LibreOffice stores Zotero citations as reference marks, which this writer does not emit.

Citation clusters are linked to your personal library. `zotero_api` can still address a group library with a `groups/GROUPID/...` path. A collaborator on another Zotero account will see the embedded citation data and can restyle it; Refresh updates the live item only for the account that owns the user ID in the URI.

## Update or remove

Update to the latest version on GitHub:

```bash
uv tool upgrade zotero-mcp
```

With pipx: `pipx upgrade zotero-mcp`. Then restart each agent, or reload its MCP servers, so that it starts the new version. On Windows a running server keeps its files open; if the upgrade reports a file in use, quit your agents and run it again.

To remove the server, run `uv tool uninstall zotero-mcp` (or `pipx uninstall zotero-mcp`) and delete the `zotero` entry from each agent's config.

Keep a single installation. Agents that point at different copies run different versions.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `Unconfigured` | The server found no usable user ID or API key. Set them as in step 2. On Windows the next request picks them up. Elsewhere, restart the agent, or put the values in its `env` block. |
| The agent cannot start the server | Use the full path of `zotero-mcp` from step 3 as the command. |
| An agent runs an older version | Run `uv tool list`, remove any other copy of the server, point every agent at the same command, and restart the agent. |
| Search is empty while the website shows items | The desktop library has other items, and this key is not in it. Sync Zotero. A missing local record is not fetched from the website, because the local library is the copy being edited. |
| Word shows `ADDIN ZOTERO_ITEM` | Field codes are visible. Press Alt+F9 (Option-Fn-F9 on a Mac), or follow the [field-code article](https://www.zotero.org/support/kb/word_field_codes). |
| Zotero asks you to pick a style | The document has no `ZOTERO_PREF_*` properties. Run `embed_zotero_word_fields` again. |
| Refresh does not update a title you edited in Zotero | The user ID in the field does not match the account signed in to the desktop app, or the item key is not in that library. |

## Development

```bash
git clone https://github.com/Jayaram-Nambiar/zotero-mcp.git
cd zotero-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m unittest discover -s tests
```

On macOS and Linux the interpreter is `.venv/bin/python`. The tests run offline. Agents keep running the copy installed in step 3, so upgrade it after a change reaches GitHub. [CONTRIBUTING.md](CONTRIBUTING.md) lists the rules for changes.

## Acknowledgements

- [Zotero](https://www.zotero.org/) is developed by the Corporation for Digital Scholarship. The local API, Web API, and Word plugin are theirs.
- The [Model Context Protocol](https://modelcontextprotocol.io/) defines how this server talks to agents.
- Citation formatting uses the [Citation Style Language](https://citationstyles.org/).
- Word documents are written with [python-docx](https://python-docx.readthedocs.io/).

## Disclaimer

This project is not affiliated with, endorsed by, or supported by Zotero or the Corporation for Digital Scholarship. Zotero is a trademark of the Corporation for Digital Scholarship. Use of the Zotero API is subject to Zotero's own terms and documentation. You are responsible for the API key you create and for the library changes an agent makes with it.

The Word fields follow the field format Zotero documents and that its Word plugin reads. Refresh the document in Word before you rely on the citation style.

## License

[MIT](LICENSE). Copyright (c) 2026 Jayaram Nambiar.
