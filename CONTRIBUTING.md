# Contributing

This repository is meant to stay small enough for a later agent or a person to change safely.

1. Run `python -m unittest discover -s tests` before you commit.
2. Keep tool names aligned with what they do. `search_zotero` searches. `embed_zotero_word_fields` writes Word fields. A rename is a breaking change: record it in `CHANGELOG.md`.
3. The Word field text is a compatibility contract. `tests/test_word.py` checks the `ADDIN ZOTERO_ITEM CSL_CITATION` and `ADDIN ZOTERO_BIBL` instructions and the `ZOTERO_PREF_*` properties. Update those tests in the same change as the writer.
4. Do not copy Zotero's source into this repository. Zotero is licensed under the GNU AGPL. This project is MIT and implements the documented field format itself.
5. Do not commit API keys, user IDs, `.env` files, or sample documents from a real library.
6. Bump `version` in `pyproject.toml` and `__version__` in `src/zotero_mcp/__init__.py` together.
