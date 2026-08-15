import json
import tempfile
import unittest
from pathlib import Path


from src.database.staging_connection import (
    get_staging_connection,
    initialize_staging_database,
)
from src.extraction.candidate_import import (
    CandidateImportError,
    import_candidate_bundle,
)
from src.validation.candidates import list_candidates


class CandidateImportTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.staging_path = self.root / "staging.db"
        initialize_staging_database(self.staging_path)
        self.connection = get_staging_connection(self.staging_path)

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def _write_bundle(self, candidates):
        path = self.root / "bundle.json"
        path.write_text(
            json.dumps(
                {
                    "person_id": 1,
                    "source_id": 2,
                    "candidates": candidates,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_imports_structured_candidates(self):
        bundle = self._write_bundle(
            [
                {
                    "category": "education",
                    "key": "department",
                    "value": "Example Department",
                    "visibility": "public",
                },
                {
                    "category": "skill",
                    "key": "programming_language",
                    "value": "Example Language",
                    "allow_overlap": True,
                },
            ]
        )

        result = import_candidate_bundle(
            bundle,
            connection=self.connection,
        )
        candidates = list_candidates(connection=self.connection)

        self.assertEqual(len(result["created_candidate_ids"]), 2)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_id"], 2)

    def test_reimport_skips_exact_candidates(self):
        bundle = self._write_bundle(
            [
                {
                    "category": "education",
                    "key": "department",
                    "value": "Example Department",
                }
            ]
        )
        first = import_candidate_bundle(bundle, connection=self.connection)

        second = import_candidate_bundle(bundle, connection=self.connection)

        self.assertEqual(second["created_candidate_ids"], [])
        self.assertEqual(
            second["skipped_candidate_ids"],
            first["created_candidate_ids"],
        )
        self.assertEqual(len(list_candidates(connection=self.connection)), 1)

    def test_invalid_item_rolls_back_entire_bundle(self):
        bundle = self._write_bundle(
            [
                {
                    "category": "education",
                    "key": "department",
                    "value": "Example Department",
                },
                {
                    "category": None,
                    "key": "invalid",
                    "value": "Invalid",
                },
            ]
        )

        with self.assertRaises(CandidateImportError):
            import_candidate_bundle(bundle, connection=self.connection)

        self.assertEqual(list_candidates(connection=self.connection), [])

    def test_rejects_invalid_bundle_shape(self):
        path = self.root / "invalid.json"
        path.write_text('{"person_id": 1, "source_id": 2}', encoding="utf-8")

        with self.assertRaises(CandidateImportError):
            import_candidate_bundle(path, connection=self.connection)


if __name__ == "__main__":
    unittest.main()
