# zotero-mcp

A [Model Context Protocol](https://modelcontextprotocol.io/) server for one person's Zotero library. It can search the library, call the [Zotero Web API v3](https://www.zotero.org/support/dev/web_api/v3/basics), and write Microsoft Word fields that the [Zotero Word plugin](https://www.zotero.org/support/word_processor_plugin_usage) can refresh and restyle.

There is no operating-system setting that every coding agent reads. Install this package once, put your Zotero user ID and API key in your user environment, and point each agent at the same command:

```bash
python -m zotero_mcp
```

The process speaks MCP on stdin and stdout. Start it from the agent, not in a terminal where you expect a prompt.

## What you need

- Python 3.10 or newer on `PATH` (`python` or, on Windows, `py -3`)
- The [Zotero desktop app](https://www.zotero.org/download/) for fast local reads
- A [zotero.org](https://www.zotero.org/user/register) account, its numeric user ID, and an API key
- For Word citations: Microsoft Word and the [Zotero word-processor plugin](https://www.zotero.org/support/word_processor_plugin_installation)

Reads try the desktop app at `http://127.0.0.1:23119/api` first. Zotero documents that local API as `localhost` port `23119`. This server uses `127.0.0.1` so an IPv6 localhost lookup does not stall. If the app is closed, or its library has no items yet, reads use `https://api.zotero.org`. Writes always use `api.zotero.org`, then sync back to the desktop app.

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

Pick one place. Do not commit either value.

**User environment (one copy for every agent that inherits it).** Restart the agent after setting these.

Windows PowerShell:

```powershell
[Environment]::SetEnvironmentVariable("ZOTERO_USER_ID", "YOUR_USER_ID", "User")
[Environment]::SetEnvironmentVariable("ZOTERO_API_KEY", "YOUR_API_KEY", "User")
```

macOS and Linux, in `~/.zshrc` or `~/.bashrc`:

```bash
export ZOTERO_USER_ID="YOUR_USER_ID"
export ZOTERO_API_KEY="YOUR_API_KEY"
```

A macOS app started from the Dock does not read `~/.zshrc`. If an agent does not see the variables, put them in that agent's `env` block below.

**Client config.** Paste the values only into the config file for that agent. Prefer the environment-variable reference when the client supports it, so the key is not stored twice.

`.env.example` shows the variable names. This server does not load a `.env` file on its own.

## 3. Install

```bash
python -m pip install "git+https://github.com/Jayaram-Nambiar/zotero-mcp.git"
python -c "import zotero_mcp; print(zotero_mcp.__version__)"
```

On Windows, if `python` is the Microsoft Store alias, use `py -3` in place of `python` in every snippet below.

From a clone:

```bash
git clone https://github.com/Jayaram-Nambiar/zotero-mcp.git
cd zotero-mcp
python -m pip install .
```

## 4. Connect an agent

Use the same server name, `zotero`, everywhere. After saving a config, reload MCP servers or restart the agent. The first successful `search_zotero` call confirms the setup.

### Cursor

Global file, used by every project: `~/.cursor/mcp.json` on macOS and Linux, `%USERPROFILE%\.cursor\mcp.json` on Windows. A project file `.cursor/mcp.json` overrides it for that project. Cursor documents both in [MCP](https://cursor.com/docs/mcp).

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["-m", "zotero_mcp"],
      "env": {
        "ZOTERO_USER_ID": "${env:ZOTERO_USER_ID}",
        "ZOTERO_API_KEY": "${env:ZOTERO_API_KEY}"
      }
    }
  }
}
```

### Claude Code

User scope is available in every project. Claude Code documents the command and scopes in [MCP servers](https://code.claude.com/docs/en/mcp-servers).

```bash
claude mcp add --scope user --transport stdio zotero -- python -m zotero_mcp
```

If the variables are not already in the environment Claude Code sees:

```bash
claude mcp add --scope user --transport stdio --env ZOTERO_USER_ID=YOUR_USER_ID --env ZOTERO_API_KEY=YOUR_API_KEY zotero -- python -m zotero_mcp
```

A project file `.mcp.json` can be committed when it contains references rather than the key:

```json
{
  "mcpServers": {
    "zotero": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "zotero_mcp"],
      "env": {
        "ZOTERO_USER_ID": "${ZOTERO_USER_ID}",
        "ZOTERO_API_KEY": "${ZOTERO_API_KEY}"
      }
    }
  }
}
```

### ChatGPT and Codex

The ChatGPT desktop app, the Codex CLI, and the Codex IDE extension share `~/.codex/config.toml`. A trusted project can also use `.codex/config.toml`. OpenAI documents this in [Model Context Protocol](https://learn.chatgpt.com/docs/extend/mcp) and the [configuration reference](https://developers.openai.com/codex/config-reference). The ChatGPT website chat does not launch a local program; use the desktop app or Codex.

`env_vars` forwards variables that are already set, so the key stays out of the file:

```toml
[mcp_servers.zotero]
command = "python"
args = ["-m", "zotero_mcp"]
env_vars = ["ZOTERO_USER_ID", "ZOTERO_API_KEY"]
startup_timeout_sec = 30
```

Or from the CLI:

```bash
codex mcp add zotero -- python -m zotero_mcp
```

### Google Antigravity

Antigravity documents MCP in [its MCP guide](https://antigravity.google/docs/mcp/). The global file is `~/.gemini/config/mcp_config.json` (`%USERPROFILE%\.gemini\config\mcp_config.json` on Windows). A workspace file is `.agents/mcp_config.json`. You can also open Manage MCP Servers and edit the raw config.

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["-m", "zotero_mcp"],
      "env": {
        "ZOTERO_USER_ID": "YOUR_USER_ID",
        "ZOTERO_API_KEY": "YOUR_API_KEY"
      }
    }
  }
}
```

### VS Code with GitHub Copilot

Workspace file `.vscode/mcp.json`, or the user `mcp.json` from the command MCP: Open User Configuration. The shape is documented in the [MCP configuration reference](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration). VS Code uses `servers`, not `mcpServers`.

```json
{
  "servers": {
    "zotero": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "zotero_mcp"]
    }
  }
}
```

Launch VS Code from a terminal that already has the two variables, or add an `env` object with your values. Do not commit that object.

### Claude Desktop

| System | File |
| --- | --- |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["-m", "zotero_mcp"],
      "env": {
        "ZOTERO_USER_ID": "YOUR_USER_ID",
        "ZOTERO_API_KEY": "YOUR_API_KEY"
      }
    }
  }
}
```

### Perplexity

Perplexity's published MCP docs describe connecting *to* Perplexity from another client: [Perplexity MCP server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server) and [Computer](https://docs.perplexity.ai/docs/getting-started/integrations/computer-mcp-server). They do not document loading this local stdio server into the Perplexity app. If a Perplexity client later accepts a local `mcpServers` command, use the same `python -m zotero_mcp` entry as Cursor.

### Any other MCP client

A client that can launch a stdio server needs:

| Setting | Value |
| --- | --- |
| Command | `python` |
| Arguments | `-m`, `zotero_mcp` |
| Environment | `ZOTERO_USER_ID`, `ZOTERO_API_KEY` |

The transport is stdio. This package does not open a network port.

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

From Python, with the same environment variables:

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

The writer covers body paragraphs, table cells, headers, and footers. It does not scan footnotes or text boxes. A paragraph that contains a marker is rewritten as ordinary runs plus fields, so mixed bold or italic in that paragraph is not kept. The fields are in-text Word fields. LibreOffice stores Zotero citations as reference marks, which this writer does not emit.

Citation clusters are linked to your personal library. `zotero_api` can still address a group library with a `groups/GROUPID/...` path. A collaborator on another Zotero account will see the embedded citation data and can restyle it; Refresh updates the live item only for the account that owns the user ID in the URI.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `Unconfigured` | The agent process cannot see `ZOTERO_USER_ID` or `ZOTERO_API_KEY`. Restart it after changing user variables, or set `env` in that agent's config. |
| Search is empty while the website shows items | The desktop library has other items, and this key is not in it. Sync Zotero. A missing local record is not fetched from the website, because the local library is the copy being edited. |
| Word shows `ADDIN ZOTERO_ITEM` | Field codes are visible. Press Alt+F9 (Option-Fn-F9 on a Mac), or follow the [field-code article](https://www.zotero.org/support/kb/word_field_codes). |
| Zotero asks you to pick a style | The document has no `ZOTERO_PREF_*` properties. Run `embed_zotero_word_fields` again. |
| Refresh does not update a title you edited in Zotero | The user ID in the field does not match the account signed in to the desktop app, or the item key is not in that library. |

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests
```

`CONTRIBUTING.md` is the maintenance note for the next person or agent.

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
