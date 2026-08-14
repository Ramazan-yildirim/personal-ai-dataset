import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


from src.database.sources import (
    DuplicateSourceError,
    SourceNotFoundError,
    SourceValidationError,
    add_source,
    compute_file_hash,
    deactivate_source,
    get_source,
    list_sources,
)


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class SourcesTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.source_path = Path(self.temporary_directory.name) / "example.txt"
        self.source_path.write_text("Synthetic source content.", encoding="utf-8")

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_compute_file_hash_streams_expected_sha256(self):
        expected = hashlib.sha256(b"Synthetic source content.").hexdigest()

        result = compute_file_hash(self.source_path, chunk_size=4)

        self.assertEqual(result, expected)

    def test_add_source_hashes_file_and_normalizes_type(self):
        source = add_source(
            "  CV  ",
            "Synthetic CV",
            file_path=self.source_path,
            source_date="2026-01-15",
            connection=self.connection,
        )

        self.assertEqual(source["source_type"], "cv")
        self.assertEqual(source["title"], "Synthetic CV")
        self.assertEqual(source["source_date"], "2026-01-15")
        self.assertEqual(source["file_hash"], compute_file_hash(self.source_path))
        self.assertEqual(source["is_active"], 1)

    def test_duplicate_file_content_is_rejected_across_paths(self):
        second_path = Path(self.temporary_directory.name) / "copy.txt"
        second_path.write_text("Synthetic source content.", encoding="utf-8")
        first = add_source(
            "cv",
            "First Synthetic CV",
            file_path=self.source_path,
            connection=self.connection,
        )

        with self.assertRaises(DuplicateSourceError) as context:
            add_source(
                "other",
                "Copied Synthetic CV",
                file_path=second_path,
                connection=self.connection,
            )

        self.assertEqual(context.exception.source["id"], first["id"])

    def test_duplicate_manual_source_metadata_is_rejected(self):
        add_source(
            "manual",
            "Synthetic statement",
            source_date="2026-01-01",
            connection=self.connection,
        )

        with self.assertRaises(DuplicateSourceError):
            add_source(
                "manual",
                "Synthetic statement",
                source_date="2026-01-01",
                connection=self.connection,
            )

    def test_deactivate_source_preserves_history_and_active_filter(self):
        first = add_source(
            "manual",
            "First synthetic statement",
            connection=self.connection,
        )
        second = add_source(
            "manual",
            "Second synthetic statement",
            connection=self.connection,
        )

        deactivated = deactivate_source(first["id"], connection=self.connection)
        all_sources = list_sources(connection=self.connection)
        active_sources = list_sources(active_only=True, connection=self.connection)

        self.assertEqual(deactivated["is_active"], 0)
        self.assertEqual(len(all_sources), 2)
        self.assertEqual([source["id"] for source in active_sources], [second["id"]])
        self.assertEqual(
            get_source(first["id"], connection=self.connection)["is_active"],
            0,
        )

    def test_rejects_invalid_source_input(self):
        with self.assertRaises(SourceValidationError):
            add_source("", "Title", connection=self.connection)
        with self.assertRaises(SourceValidationError):
            add_source(
                "cv",
                "Title",
                source_date="2026-99-01",
                connection=self.connection,
            )
        with self.assertRaises(SourceValidationError):
            add_source(
                "cv",
                "Missing file",
                file_path=Path(self.temporary_directory.name) / "missing.txt",
                connection=self.connection,
            )
        with self.assertRaises(SourceValidationError):
            add_source(
                "cv",
                "Hash mismatch",
                file_path=self.source_path,
                file_hash="wrong",
                connection=self.connection,
            )

    def test_unknown_source_raises(self):
        with self.assertRaises(SourceNotFoundError):
            get_source(999, connection=self.connection)


if __name__ == "__main__":
    unittest.main()
