# Changelog

## 1.0.1

- `embed_zotero_word_fields` no longer fails with `No Zotero item was loaded for …` on documents with more than a few citation markers. The pass that collects item keys skipped marker paragraphs, so their items were never fetched.

## 1.0.0

First public release.

- Search, list, and fetch items from the local Zotero app or api.zotero.org.
- Call the Zotero Web API, including guarded deletes and attachment upload.
- Write Microsoft Word citation and bibliography fields, plus `ZOTERO_PREF_*` document preferences, so the Zotero Word plugin can refresh them.
