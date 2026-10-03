# Security policy

## Supported versions

Only the latest release receives security fixes. Update with `uv tool upgrade zotero-mcp`; if you pinned a version, install the newer release's tag instead. The [README](README.md#update-pin-or-remove) describes both.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Earlier releases | No |

## Report a vulnerability

Please do not describe a vulnerability in a public issue. Instead, [open an issue](https://github.com/Jayaram-Nambiar/zotero-mcp/issues/new) titled "Security report" that contains no details, and ask for a private way to send them. The maintainer will reply with one.

When you send the details, include:

- the affected version, from `uv tool list`, and your operating system;
- the steps to reproduce the problem, and its impact;
- a suggested fix, if you have one.

Never send your Zotero API key. If a key may have leaked, revoke it first.

## Protect your Zotero API key

- Create a separate key for this server, with only the access your agents need. Leave write access off unless agents must change your library: a key with write access can change or delete library data.
- Store the key in your user environment variables ([README, Step 2](README.md#step-2-store-your-user-id-and-api-key)), not in files you share or commit. Prefer agent configs that reference the variable over configs that hold the value: `${env:ZOTERO_API_KEY}` in Cursor, `env_vars` in Codex, and `{env:ZOTERO_API_KEY}` in opencode. Keep any config file that holds the key itself private.
- If the key appears in a chat, a committed file, a log, or a screenshot, revoke it on the [API keys page](https://www.zotero.org/settings/keys) and create a new one. Store the new key as in Step 2, update every config file that held the old one, and restart your agents.

## Safeguards in the server

- The server reads the key from its process environment and, on Windows, from your user or system environment variables when the agent does not pass it. A user ID that is not all digits, or a key that is not all letters and digits, counts as missing, so a malformed value never reaches a request header or an error message.
- It sends the key only as the `Zotero-API-Key` header to `api.zotero.org`. It never accepts the key as a tool argument or returns it in a result. It never sends the key to the local Zotero app, to the file-storage address used for uploads, or to another host that a response redirects to.
- It removes the key from error messages and response bodies before returning them.
- `zotero_api` accepts only relative Zotero API paths and refuses Zotero's key endpoints, so an agent can neither read the key's details nor send the key to another host.
- `zotero_api` refuses `DELETE` unless `confirm_delete` is true. This is a guardrail, not a substitute for a key without write access.
- `upload_zotero_file` and `embed_zotero_word_fields` read the local files you name, by full path only. Point them only at files you intend to upload or convert. `upload_zotero_file` never replaces a file an attachment already has. `embed_zotero_word_fields` writes a new document and never changes the original; it overwrites another existing file only when that file is named as the output.
