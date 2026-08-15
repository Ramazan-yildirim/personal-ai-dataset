import sqlite3
import tempfile
import unittest
from pathlib import Path


from src.database.sources import list_sources
from src.ingestion.documents import (
    IngestionValidationError,
    ingest_document,
)


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class IngestionTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.input_root = temporary_root / "incoming"
        self.raw_root = temporary_root / "raw"
        self.input_root.mkdir()

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_ingest_copies_document_and_registers_source(self):
        document = self.input_root / "example_cv.txt"
        document.write_text("Synthetic CV content.", encoding="utf-8")

        result = ingest_document(
            "cv",
            "Synthetic CV",
            document,
            source_date="2026-01-15",
            raw_root=self.raw_root,
            connection=self.connection,
        )
        copied_path = self.raw_root / "cv" / "example_cv.txt"

        self.assertTrue(copied_path.exists())
        self.assertTrue(result["copied"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["source"]["source_type"], "cv")
        self.assertIsNotNone(result["source"]["file_hash"])

    def test_duplicate_content_is_idempotent(self):
        document = self.input_root / "example.txt"
        document.write_text("Same synthetic content.", encoding="utf-8")
        first = ingest_document(
            "other",
            "First title",
            document,
            raw_root=self.raw_root,
            connection=self.connection,
        )

        second = ingest_document(
            "other",
            "Second title",
            document,
            raw_root=self.raw_root,
            connection=self.connection,
        )

        self.assertEqual(second["source"]["id"], first["source"]["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(list_sources(connection=self.connection)), 1)

    def test_same_filename_with_different_content_preserves_both(self):
        first_directory = self.input_root / "first"
        second_directory = self.input_root / "second"
        first_directory.mkdir()
        second_directory.mkdir()
        first_document = first_directory / "document.txt"
        second_document = second_directory / "document.txt"
        first_document.write_text("First synthetic version.", encoding="utf-8")
        second_document.write_text("Second synthetic version.", encoding="utf-8")

        first = ingest_document(
            "other",
            "First version",
            first_document,
            raw_root=self.raw_root,
            connection=self.connection,
        )
        second = ingest_document(
            "other",
            "Second version",
            second_document,
            raw_root=self.raw_root,
            connection=self.connection,
        )

        self.assertNotEqual(first["raw_path"], second["raw_path"])
        self.assertTrue(Path(first["raw_path"]).exists())
        self.assertTrue(Path(second["raw_path"]).exists())
        self.assertIn("_", Path(second["raw_path"]).stem)

    def test_document_already_in_raw_storage_is_not_copied(self):
        raw_directory = self.raw_root / "portfolio"
        raw_directory.mkdir(parents=True)
        document = raw_directory / "portfolio.md"
        document.write_text("# Synthetic Portfolio", encoding="utf-8")

        result = ingest_document(
            "portfolio",
            "Synthetic Portfolio",
            document,
            raw_root=self.raw_root,
            connection=self.connection,
        )

        self.assertFalse(result["copied"])
        self.assertEqual(Path(result["raw_path"]), document)

    def test_rejects_missing_unsupported_and_unknown_type(self):
        unsupported = self.input_root / "program.exe"
        unsupported.write_bytes(b"synthetic")

        with self.assertRaises(IngestionValidationError):
            ingest_document(
                "other",
                "Missing",
                self.input_root / "missing.txt",
                raw_root=self.raw_root,
                connection=self.connection,
            )
        with self.assertRaises(IngestionValidationError):
            ingest_document(
                "other",
                "Unsupported",
                unsupported,
                raw_root=self.raw_root,
                connection=self.connection,
            )
        with self.assertRaises(IngestionValidationError):
            ingest_document(
                "unknown",
                "Unknown",
                unsupported,
                raw_root=self.raw_root,
                connection=self.connection,
            )


if __name__ == "__main__":
    unittest.main()
