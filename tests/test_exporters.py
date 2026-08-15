import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


from src.database.fact_sources import link_fact_source
from src.database.facts import add_fact
from src.database.persons import create_person
from src.database.sources import add_source
from src.exporters.common import ExportValidationError, load_export_facts
from src.exporters.finetuning import export_finetuning
from src.exporters.rag import chunk_text, export_rag
from src.exporters.transformer import export_transformer


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class ExportersTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

        person = create_person("Example User", connection=self.connection)
        self.person_id = person["id"]
        self.public_fact_id = add_fact(
            self.person_id,
            "education",
            "department",
            "Example Department",
            valid_from="2024-09-01",
            visibility="public",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "skill",
            "programming_language",
            "Example Language",
            visibility="public",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "profile",
            "private_note",
            "Private Synthetic Value",
            visibility="private",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "profile",
            "internal_note",
            "Internal Synthetic Value",
            visibility="internal",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "profile",
            "deprecated_note",
            "Deprecated Synthetic Value",
            status="deprecated",
            connection=self.connection,
        )
        source = add_source(
            "manual",
            "Synthetic statement",
            connection=self.connection,
        )
        self.source_id = source["id"]
        link_fact_source(
            self.public_fact_id,
            self.source_id,
            connection=self.connection,
        )

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_transformer_export_is_public_by_default(self):
        supplemental = self.root / "supplemental"
        supplemental.mkdir()
        (supplemental / "corpus.txt").write_text(
            "Synthetic supplemental corpus.",
            encoding="utf-8",
        )
        output = self.root / "transformer"

        result = export_transformer(
            output_dir=output,
            supplemental_dir=supplemental,
            connection=self.connection,
        )
        personal = (output / "personal_corpus.txt").read_text(encoding="utf-8")
        full = (output / "full_corpus.txt").read_text(encoding="utf-8")

        self.assertEqual(result["fact_count"], 2)
        self.assertIn("Example Department", personal)
        self.assertNotIn("Private Synthetic Value", personal)
        self.assertNotIn("Internal Synthetic Value", personal)
        self.assertNotIn("Deprecated Synthetic Value", personal)
        self.assertNotIn("supplemental", personal)
        self.assertIn("Synthetic supplemental corpus.", full)

    def test_finetuning_export_is_deterministic_and_filtered(self):
        output = self.root / "finetuning"

        first = export_finetuning(
            output_dir=output,
            connection=self.connection,
        )
        first_contents = {
            path.name: path.read_bytes()
            for path in output.glob("*.jsonl")
        }
        second = export_finetuning(
            output_dir=output,
            connection=self.connection,
        )
        second_contents = {
            path.name: path.read_bytes()
            for path in output.glob("*.jsonl")
        }
        all_text = b"".join(second_contents.values()).decode("utf-8")

        self.assertEqual(first["fact_count"], 2)
        self.assertEqual(second["fact_count"], 2)
        self.assertEqual(first_contents, second_contents)
        self.assertNotIn("Private Synthetic Value", all_text)
        self.assertIn('"messages"', all_text)

    def test_finetuning_keeps_train_nonempty_for_tiny_dataset(self):
        output = self.root / "tiny-finetuning"

        result = export_finetuning(
            output_dir=output,
            seed="seed-10",
            connection=self.connection,
        )

        self.assertGreater(result["files"]["train"]["record_count"], 0)

    def test_rag_export_preserves_source_and_visibility_metadata(self):
        output = self.root / "rag"

        result = export_rag(
            output_dir=output,
            connection=self.connection,
        )
        documents = [
            json.loads(line)
            for line in (output / "documents.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        linked = next(
            document
            for document in documents
            if document["document_id"] == f"fact_{self.public_fact_id}"
        )

        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["chunk_count"], 2)
        self.assertEqual(linked["source_ids"], [self.source_id])
        self.assertEqual(linked["visibility"], "public")

    def test_private_export_requires_explicit_opt_in(self):
        facts = load_export_facts(
            visibilities=("public", "private"),
            connection=self.connection,
        )

        values = {fact["value"] for fact in facts}
        self.assertIn("Private Synthetic Value", values)
        self.assertNotIn("Internal Synthetic Value", values)

    def test_chunk_text_validates_and_preserves_content(self):
        text = " ".join(f"word{index}" for index in range(100))

        chunks = chunk_text(text, max_chars=80, overlap_chars=10)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))
        with self.assertRaises(ExportValidationError):
            chunk_text(text, max_chars=10, overlap_chars=10)


if __name__ == "__main__":
    unittest.main()
