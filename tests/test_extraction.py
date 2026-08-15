import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from pypdf import PdfWriter


from src.database.sources import add_source
from src.extraction.documents import (
    EmptyExtractionError,
    ExtractionDependencyError,
    ExtractionIntegrityError,
    ExtractionValidationError,
    extract_source,
    extract_text,
)


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class ExtractionTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_extracts_and_normalizes_plain_text(self):
        document = self.root / "document.txt"
        document.write_text("First line.  \n\n\nSecond line.", encoding="utf-8")

        text = extract_text(document)

        self.assertEqual(text, "First line.\n\nSecond line.")

    def test_extracts_visible_html_without_script_or_style(self):
        document = self.root / "page.html"
        document.write_text(
            "<html><style>hidden</style><body><h1>Title</h1>"
            "<p>Visible text.</p><script>ignored()</script></body></html>",
            encoding="utf-8",
        )

        text = extract_text(document)

        self.assertIn("Title", text)
        self.assertIn("Visible text.", text)
        self.assertNotIn("hidden", text)
        self.assertNotIn("ignored", text)

    def test_extracts_json_deterministically(self):
        document = self.root / "data.json"
        document.write_text('{"z": 1, "a": "Synthetic"}', encoding="utf-8")

        text = extract_text(document)

        self.assertLess(text.index('"a"'), text.index('"z"'))

    def test_extracts_docx_with_standard_library_adapter(self):
        document = self.root / "document.docx"
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("word/document.xml", xml)

        text = extract_text(document)

        self.assertEqual(text, "First paragraph.\nSecond paragraph.")

    def test_image_requires_future_ocr_adapter(self):
        document = self.root / "scan.png"
        document.write_bytes(b"synthetic image")

        with self.assertRaises(ExtractionDependencyError):
            extract_text(document)

    def test_pdf_adapter_rejects_document_without_text_layer(self):
        document = self.root / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with document.open("wb") as stream:
            writer.write(stream)

        with self.assertRaises(EmptyExtractionError):
            extract_text(document)

    def test_extract_source_writes_staging_payload(self):
        document = self.root / "source.md"
        document.write_text("# Synthetic Source\n\nContent.", encoding="utf-8")
        source = add_source(
            "portfolio",
            "Synthetic Source",
            file_path=document,
            connection=self.connection,
        )
        output_root = self.root / "extracted"

        result = extract_source(
            source["id"],
            output_root=output_root,
            connection=self.connection,
        )
        payload = json.loads(
            Path(result["output_path"]).read_text(encoding="utf-8")
        )

        self.assertEqual(payload["source_id"], source["id"])
        self.assertEqual(payload["text"], "# Synthetic Source\n\nContent.")
        self.assertEqual(payload["file_hash"], source["file_hash"])

    def test_extract_source_detects_raw_document_mutation(self):
        document = self.root / "source.txt"
        document.write_text("Original synthetic content.", encoding="utf-8")
        source = add_source(
            "other",
            "Synthetic Source",
            file_path=document,
            connection=self.connection,
        )
        document.write_text("Changed synthetic content.", encoding="utf-8")

        with self.assertRaises(ExtractionIntegrityError):
            extract_source(
                source["id"],
                output_root=self.root / "extracted",
                connection=self.connection,
            )

    def test_rejects_invalid_docx(self):
        document = self.root / "invalid.docx"
        document.write_bytes(b"not a zip")

        with self.assertRaises(ExtractionValidationError):
            extract_text(document)


if __name__ == "__main__":
    unittest.main()
