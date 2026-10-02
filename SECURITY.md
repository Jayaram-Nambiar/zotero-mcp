# Security

Report a vulnerability through GitHub private security advisories for this repository, or by opening an issue that does not include secrets.

- Keep `ZOTERO_API_KEY` in your user environment variables, or in an agent config that is never committed. Prefer configs that reference the variable (`${env:ZOTERO_API_KEY}` in Cursor, `env_vars` in Codex, `{env:ZOTERO_API_KEY}` in opencode) over configs that hold the value.
- The server reads the key from its process environment and, on Windows, from your user or system environment variables when the agent does not pass it. It sends the key only as the `Zotero-API-Key` header to `api.zotero.org`, never as a tool argument or result, and never to the local Zotero app or the file-storage URL used for uploads.
- A key with write access can change or delete library data. Create a separate key for this server and enable write access only if you need it.
- `zotero_api` refuses `DELETE` unless `confirm_delete` is true. That check is a guardrail, not a substitute for a limited key.
- The server refuses Zotero key endpoints and removes the API key from error text it returns.
- `upload_zotero_file` and `embed_zotero_word_fields` read local paths you pass to them. Point them only at files you intend to send or rewrite.
- If a key appears in a chat, a committed file, or a screenshot, revoke it at <https://www.zotero.org/settings/keys> and create a new one.
