"""Word field tests. They build a .docx and do not call Zotero."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from docx import Document

from zotero_mcp.server import embed_zotero_word_fields
from zotero_mcp.word import (
    EmbeddedItem,
    chunk_property,
    citation_instruction,
    document_preferences,
    embed_document,
    parse_marker_body,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _sample_item(title: str = "Example & <Trial>") -> EmbeddedItem:
    return EmbeddedItem(
        csl={
            "type": "article-journal",
            "title": title,
            "author": [{"family": "Smith", "given": "Ada"}],
            "issued": {"date-parts": [[2020]]},
        },
        bibliography="Smith A. Example. Journal. 2020.",
    )


class WordFieldTests(unittest.TestCase):
    def test_marker_options(self) -> None:
        marker = parse_marker_body("ABCD1234+EFGH5678|locator=12|label=page|prefix=see")
        self.assertEqual(marker.kind, "citation")
        assert marker.citation is not None
        self.assertEqual(marker.citation.keys, ["ABCD1234", "EFGH5678"])
        self.assertEqual(marker.citation.locator, "12")
        self.assertEqual(marker.citation.prefix, "see")
        with self.assertRaises(ValueError):
            parse_marker_body("not-a-key")

    def test_preferences_chunk_at_255_characters(self) -> None:
        chunks = chunk_property("a" * 256)
        self.assertEqual(chunks, ["a" * 255, "a"])
        raw = document_preferences(style="vancouver", locale="en-US", session_id="abc", has_bibliography=True)
        payload = json.loads("".join(chunk_property(raw)))
        self.assertEqual(payload["dataVersion"], 4)
        self.assertEqual(payload["prefs"]["fieldType"], "Field")
        self.assertEqual(payload["style"]["styleID"], "http://www.zotero.org/styles/vancouver")
        self.assertFalse(payload["style"]["bibliographyStyleHasBeenSet"])

    def test_docx_contains_plugin_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "draft.docx"
            destination = root / "draft.zotero.docx"
            document = Document()
            document.add_paragraph("Before {{zotero:ABCD1234|locator=4|label=page}} after.")
            document.add_paragraph("{{zotero:bibliography}}")
            document.core_properties.author = "Local User"
            document.save(source)
            stats = embed_document(
                source,
                destination,
                user_id="1",
                style="vancouver",
                locale="en-US",
                items={"ABCD1234": _sample_item()},
                insert_bibliography=True,
            )
            self.assertEqual(stats.citation_count, 1)
            self.assertTrue(stats.bibliography_inserted)
            self.assertEqual(Document(source).paragraphs[0].text, "Before {{zotero:ABCD1234|locator=4|label=page}} after.")
            with zipfile.ZipFile(destination) as package:
                codes = _field_codes(package.read("word/document.xml"))
                preferences = _preferences(package.read("docProps/custom.xml"))
                core = package.read("docProps/core.xml").decode("utf-8")
            self.assertTrue(codes[0].startswith(" ADDIN ZOTERO_ITEM CSL_CITATION "))
            self.assertTrue(codes[0].endswith(" "))
            citation = json.loads(codes[0][codes[0].index("{") : codes[0].rindex("}") + 1])
            self.assertEqual(citation["schema"], "https://github.com/citation-style-language/schema/raw/master/csl-citation.json")
            self.assertEqual(citation["citationItems"][0]["uris"], ["http://zotero.org/users/1/items/ABCD1234"])
            self.assertEqual(citation["citationItems"][0]["locator"], "4")
            self.assertEqual(citation["properties"]["plainCitation"], "1, p. 4")
            self.assertIn("Example & <Trial>", json.dumps(citation))
            self.assertTrue(codes[1].startswith(" ADDIN ZOTERO_BIBL "))
            self.assertTrue(codes[1].rstrip().endswith("CSL_BIBLIOGRAPHY"))
            self.assertEqual(preferences["prefs"]["noteType"], 0)
            self.assertTrue(preferences["style"]["hasBibliography"])
            self.assertNotIn("Local User", core)

    def test_embed_tool_requires_user_id(self) -> None:
        previous = os.environ.pop("ZOTERO_USER_ID", None)
        try:
            result = embed_zotero_word_fields("draft.docx")
        finally:
            if previous is not None:
                os.environ["ZOTERO_USER_ID"] = previous
        self.assertEqual(result.status, "Unconfigured")

    def test_instruction_is_plugin_shaped(self) -> None:
        from zotero_mcp.word import _Job

        job = _Job(
            user_id="1",
            style_id="http://www.zotero.org/styles/apa",
            locale="en-US",
            items={"ABCD1234": _sample_item("Title")},
            order={"ABCD1234": 1},
            numeric=False,
            session_id="session",
        )
        marker = parse_marker_body("ABCD1234")
        assert marker.citation is not None
        instruction = citation_instruction(job, marker.citation, "(Smith, 2020)")
        self.assertIn(" ADDIN ZOTERO_ITEM CSL_CITATION ", instruction)


def _field_codes(document_xml: bytes) -> list[str]:
    root = ElementTree.fromstring(document_xml)
    codes = []
    for paragraph in root.iter(f"{{{_W}}}p"):
        texts = [node.text or "" for node in paragraph.iter(f"{{{_W}}}instrText")]
        if texts:
            codes.append("".join(texts))
    return codes


def _preferences(custom_xml: bytes) -> dict:
    root = ElementTree.fromstring(custom_xml)
    chunks = []
    for child in root:
        name = child.attrib.get("name", "")
        if not name.startswith("ZOTERO_PREF_"):
            continue
        chunks.append((int(name.rsplit("_", 1)[-1]), "".join(child.itertext())))
    return json.loads("".join(text for _index, text in sorted(chunks)))


if __name__ == "__main__":
    unittest.main()
