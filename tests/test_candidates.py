import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from src.database.fact_sources import FactSourceError, get_sources_for_fact
from src.database.facts import get_fact_history
from src.database.persons import create_person
from src.database.sources import add_source
from src.database.staging_connection import (
    attach_core_database,
    get_staging_connection,
    initialize_staging_database,
)
from src.validation.candidates import (
    CandidateStateError,
    CandidateValidationFailedError,
    approve_candidate,
    create_candidate,
    get_candidate,
    list_candidates,
    reject_candidate,
    validate_candidate,
)
from src.validation import candidates as candidates_module


CORE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"
)


class CandidatesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_path = Path(self.temporary_directory.name)
        self.core_path = temporary_path / "core.db"
        self.staging_path = temporary_path / "staging.db"

        core_connection = sqlite3.connect(self.core_path)
        core_connection.row_factory = sqlite3.Row
        core_connection.executescript(
            CORE_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        person = create_person("Example User", connection=core_connection)
        source = add_source(
            "manual",
            "Synthetic statement",
            connection=core_connection,
        )
        self.person_id = person["id"]
        self.source_id = source["id"]
        core_connection.commit()
        core_connection.close()

        initialize_staging_database(self.staging_path)
        self.connection = get_staging_connection(self.staging_path)
        attach_core_database(self.connection, self.core_path)

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def _create_valid_candidate(self):
        return create_candidate(
            self.person_id,
            "education",
            "class",
            "4",
            source_id=self.source_id,
            valid_from="2026-09-01",
            visibility="private",
            confidence=0.9,
            connection=self.connection,
        )

    def test_create_candidate_does_not_write_core_fact(self):
        candidate = self._create_valid_candidate()

        history = get_fact_history(
            self.person_id,
            "education",
            "class",
            connection=self.connection,
        )

        self.assertEqual(candidate["review_status"], "pending")
        self.assertEqual(candidate["validation_status"], "pending")
        self.assertEqual(history, [])

    def test_validate_candidate_is_dry_run(self):
        candidate = self._create_valid_candidate()

        validated = validate_candidate(
            candidate["id"],
            connection=self.connection,
        )
        history = get_fact_history(
            self.person_id,
            "education",
            "class",
            connection=self.connection,
        )

        self.assertEqual(validated["validation_status"], "valid")
        self.assertEqual(validated["validation_report"], [])
        self.assertEqual(history, [])

    def test_invalid_candidate_records_validation_report(self):
        candidate = create_candidate(
            999,
            "education",
            "class",
            "4",
            connection=self.connection,
        )

        validated = validate_candidate(
            candidate["id"],
            connection=self.connection,
        )

        self.assertEqual(validated["validation_status"], "invalid")
        self.assertEqual(
            validated["validation_report"][0]["code"],
            "PersonNotFoundError",
        )

    def test_approve_promotes_fact_and_links_source(self):
        candidate = self._create_valid_candidate()

        result = approve_candidate(
            candidate["id"],
            review_note="Synthetic approval",
            connection=self.connection,
        )
        sources = get_sources_for_fact(
            result["fact"]["id"],
            connection=self.connection,
        )

        self.assertEqual(result["candidate"]["review_status"], "approved")
        self.assertEqual(result["candidate"]["validation_status"], "valid")
        self.assertEqual(
            result["candidate"]["approved_fact_id"],
            result["fact"]["id"],
        )
        self.assertEqual([source["id"] for source in sources], [self.source_id])

    def test_invalid_candidate_cannot_be_approved(self):
        candidate = create_candidate(
            self.person_id,
            "education",
            "class",
            "4",
            visibility="secret",
            connection=self.connection,
        )

        with self.assertRaises(CandidateValidationFailedError):
            approve_candidate(candidate["id"], connection=self.connection)

        stored = get_candidate(candidate["id"], connection=self.connection)
        self.assertEqual(stored["review_status"], "pending")
        self.assertEqual(stored["validation_status"], "invalid")

    def test_reject_preserves_candidate_for_audit(self):
        candidate = self._create_valid_candidate()

        rejected = reject_candidate(
            candidate["id"],
            "Synthetic rejection reason",
            connection=self.connection,
        )

        self.assertEqual(rejected["review_status"], "rejected")
        self.assertEqual(rejected["review_note"], "Synthetic rejection reason")
        with self.assertRaises(CandidateStateError):
            approve_candidate(candidate["id"], connection=self.connection)

    def test_list_candidates_filters_workflow_state(self):
        pending = self._create_valid_candidate()
        rejected = create_candidate(
            self.person_id,
            "skill",
            "programming_language",
            "Synthetic Language",
            connection=self.connection,
        )
        reject_candidate(
            rejected["id"],
            "Synthetic rejection",
            connection=self.connection,
        )

        pending_records = list_candidates(
            review_status="pending",
            connection=self.connection,
        )

        self.assertEqual([record["id"] for record in pending_records], [pending["id"]])

    def test_approval_rolls_back_core_fact_when_link_step_fails(self):
        candidate = self._create_valid_candidate()
        real_link = candidates_module.link_fact_source
        call_count = 0

        def fail_second_link(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return real_link(*args, **kwargs)
            raise FactSourceError("Synthetic link failure")

        with patch(
            "src.validation.candidates.link_fact_source",
            side_effect=fail_second_link,
        ):
            with self.assertRaises(FactSourceError):
                approve_candidate(candidate["id"], connection=self.connection)

        history = get_fact_history(
            self.person_id,
            "education",
            "class",
            connection=self.connection,
        )
        stored = get_candidate(candidate["id"], connection=self.connection)
        self.assertEqual(history, [])
        self.assertEqual(stored["review_status"], "pending")
        self.assertIsNone(stored["approved_fact_id"])


if __name__ == "__main__":
    unittest.main()
