import sqlite3
import unittest
from pathlib import Path


from src.database.fact_sources import (
    LinkSourceNotFoundError,
    get_sources_for_fact,
    link_fact_source,
)
from src.database.facts import (
    AmbiguousFactError,
    DuplicateFactError,
    FactNotFoundError,
    FactStateError,
    FactValidationError,
    OverlappingFactError,
    PersonNotFoundError,
    add_fact,
    close_fact,
    correct_fact,
    deprecate_fact,
    get_current_facts,
    get_current_fact,
    get_fact,
    get_fact_history,
    get_fact_corrections,
    list_facts,
    soft_delete_fact,
    supersede_fact,
)
from src.database.sources import add_source


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class FactsTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        cursor = self.connection.execute(
            "INSERT INTO persons (name) VALUES (?)",
            ("Example User",),
        )
        self.person_id = cursor.lastrowid

    def tearDown(self):
        self.connection.close()

    def test_add_and_get_current_fact(self):
        fact_id = add_fact(
            self.person_id,
            "education",
            "class",
            "4",
            valid_from="2026-09-01",
            visibility="private",
            confidence=0.9,
            connection=self.connection,
        )

        fact = get_current_fact(
            self.person_id,
            "education",
            "class",
            as_of="2026-09-01",
            connection=self.connection,
        )

        self.assertEqual(fact["id"], fact_id)
        self.assertEqual(fact["value"], "4")
        self.assertEqual(fact["visibility"], "private")
        self.assertEqual(fact["confidence"], 0.9)

    def test_history_and_date_specific_queries(self):
        add_fact(
            self.person_id,
            "education",
            "class",
            "3",
            valid_from="2025-09-01",
            valid_to="2026-06-30",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "education",
            "class",
            "4",
            valid_from="2026-09-01",
            connection=self.connection,
        )

        old_fact = get_current_fact(
            self.person_id,
            "education",
            "class",
            as_of="2025-12-01",
            connection=self.connection,
        )
        gap = get_current_fact(
            self.person_id,
            "education",
            "class",
            as_of="2026-07-15",
            connection=self.connection,
        )
        new_fact = get_current_fact(
            self.person_id,
            "education",
            "class",
            as_of="2026-09-01",
            connection=self.connection,
        )
        history = get_fact_history(
            self.person_id,
            "education",
            "class",
            connection=self.connection,
        )

        self.assertEqual(old_fact["value"], "3")
        self.assertIsNone(gap)
        self.assertEqual(new_fact["value"], "4")
        self.assertEqual([fact["value"] for fact in history], ["3", "4"])

    def test_boundary_dates_are_inclusive(self):
        add_fact(
            self.person_id,
            "project",
            "status",
            "active",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
            connection=self.connection,
        )

        first_day = get_current_fact(
            self.person_id,
            "project",
            "status",
            as_of="2026-01-01",
            connection=self.connection,
        )
        last_day = get_current_fact(
            self.person_id,
            "project",
            "status",
            as_of="2026-12-31",
            connection=self.connection,
        )

        self.assertEqual(first_day["value"], "active")
        self.assertEqual(last_day["value"], "active")

    def test_rejects_invalid_values(self):
        invalid_cases = (
            {"category": "", "key": "class", "value": "4"},
            {
                "category": "education",
                "key": "class",
                "value": "4",
                "valid_from": "2026-13-01",
            },
            {
                "category": "education",
                "key": "class",
                "value": "4",
                "valid_from": "2026-09-01",
                "valid_to": "2026-01-01",
            },
            {
                "category": "education",
                "key": "class",
                "value": "4",
                "visibility": "secret",
            },
            {
                "category": "education",
                "key": "class",
                "value": "4",
                "confidence": 1.1,
            },
        )

        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(FactValidationError):
                    add_fact(
                        self.person_id,
                        connection=self.connection,
                        **values,
                    )

    def test_rejects_unknown_person(self):
        with self.assertRaises(PersonNotFoundError):
            add_fact(
                999,
                "skill",
                "programming_language",
                "Python",
                connection=self.connection,
            )

    def test_rejects_identical_duplicate(self):
        values = {
            "person_id": self.person_id,
            "category": "skill",
            "key": "programming_language",
            "value": "Python",
            "connection": self.connection,
        }
        add_fact(**values)

        with self.assertRaises(DuplicateFactError):
            add_fact(**values)

    def test_rejects_overlapping_single_value_periods(self):
        add_fact(
            self.person_id,
            "education",
            "class",
            "3",
            valid_from="2025-09-01",
            valid_to="2026-06-30",
            connection=self.connection,
        )

        with self.assertRaises(OverlappingFactError):
            add_fact(
                self.person_id,
                "education",
                "class",
                "4",
                valid_from="2026-01-01",
                connection=self.connection,
            )

    def test_intentional_multi_value_fact_is_explicit_and_ambiguous(self):
        add_fact(
            self.person_id,
            "skill",
            "programming_language",
            "Python",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "skill",
            "programming_language",
            "JavaScript",
            allow_overlap=True,
            connection=self.connection,
        )

        with self.assertRaises(AmbiguousFactError):
            get_current_fact(
                self.person_id,
                "skill",
                "programming_language",
                connection=self.connection,
            )

        history = get_fact_history(
            self.person_id,
            "skill",
            "programming_language",
            connection=self.connection,
        )
        self.assertEqual(len(history), 2)

        current_facts = get_current_facts(
            self.person_id,
            "skill",
            "programming_language",
            connection=self.connection,
        )
        self.assertEqual(
            {fact["value"] for fact in current_facts},
            {"Python", "JavaScript"},
        )

    def test_current_facts_can_filter_visibility(self):
        add_fact(
            self.person_id,
            "skill",
            "framework",
            "Example Public Framework",
            visibility="public",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "skill",
            "framework",
            "Example Private Framework",
            visibility="private",
            allow_overlap=True,
            connection=self.connection,
        )

        public_facts = get_current_facts(
            self.person_id,
            "skill",
            "framework",
            visibility="public",
            connection=self.connection,
        )

        self.assertEqual(len(public_facts), 1)
        self.assertEqual(public_facts[0]["value"], "Example Public Framework")

    def test_close_fact_preserves_history_and_ends_current_period(self):
        fact_id = add_fact(
            self.person_id,
            "project",
            "role",
            "Example Role",
            valid_from="2026-01-01",
            connection=self.connection,
        )

        closed = close_fact(
            fact_id,
            "2026-06-30",
            connection=self.connection,
        )
        after_period = get_current_fact(
            self.person_id,
            "project",
            "role",
            as_of="2026-07-01",
            connection=self.connection,
        )

        self.assertEqual(closed["valid_to"], "2026-06-30")
        self.assertIsNone(after_period)
        self.assertEqual(get_fact(fact_id, connection=self.connection)["status"], "active")

    def test_close_fact_rejects_invalid_range_and_unknown_id(self):
        fact_id = add_fact(
            self.person_id,
            "project",
            "role",
            "Example Role",
            valid_from="2026-01-01",
            connection=self.connection,
        )

        with self.assertRaises(FactValidationError):
            close_fact(fact_id, "2025-12-31", connection=self.connection)
        with self.assertRaises(FactNotFoundError):
            close_fact(999, "2026-01-01", connection=self.connection)

    def test_history_includes_inactive_records(self):
        add_fact(
            self.person_id,
            "interest",
            "topic",
            "Synthetic Topic",
            status="deprecated",
            connection=self.connection,
        )

        current = get_current_fact(
            self.person_id,
            "interest",
            "topic",
            connection=self.connection,
        )
        history = get_fact_history(
            self.person_id,
            "interest",
            "topic",
            connection=self.connection,
        )

        self.assertIsNone(current)
        self.assertEqual(history[0]["status"], "deprecated")

    def test_deprecate_and_soft_delete_preserve_record(self):
        fact_id = add_fact(
            self.person_id,
            "certificate",
            "name",
            "Synthetic Certificate",
            connection=self.connection,
        )

        deprecated = deprecate_fact(fact_id, connection=self.connection)
        deleted = soft_delete_fact(fact_id, connection=self.connection)

        self.assertEqual(deprecated["status"], "deprecated")
        self.assertEqual(deleted["status"], "deleted")
        stored = get_fact(fact_id, connection=self.connection)
        self.assertEqual(stored["value"], "Synthetic Certificate")
        with self.assertRaises(FactStateError):
            deprecate_fact(fact_id, connection=self.connection)

        self.assertEqual(
            list_facts(self.person_id, connection=self.connection),
            [],
        )
        audit_rows = list_facts(
            self.person_id,
            include_inactive=True,
            connection=self.connection,
        )
        self.assertEqual(audit_rows[0]["status"], "deleted")

    def test_correct_fact_adds_and_changes_dates_only(self):
        fact_id = add_fact(
            self.person_id,
            "profile",
            "role",
            "Synthetic Role",
            visibility="private",
            confidence=0.8,
            connection=self.connection,
        )
        source = add_source(
            "manual",
            "Synthetic source",
            connection=self.connection,
        )
        link_fact_source(
            fact_id,
            source["id"],
            connection=self.connection,
        )

        first = correct_fact(
            fact_id,
            valid_from="2025-01-01",
            correction_note="Missing date added",
            connection=self.connection,
        )
        second = correct_fact(
            fact_id,
            valid_from="2025-02-01",
            valid_to="2025-12-31",
            correction_note="Date corrected",
            connection=self.connection,
        )

        self.assertEqual(first["correction"]["changed_fields"], ["valid_from"])
        self.assertEqual(second["fact"]["valid_from"], "2025-02-01")
        self.assertEqual(second["fact"]["valid_to"], "2025-12-31")
        self.assertEqual(second["fact"]["value"], "Synthetic Role")
        self.assertEqual(second["fact"]["visibility"], "private")
        self.assertEqual(second["fact"]["confidence"], 0.8)
        linked = get_sources_for_fact(fact_id, connection=self.connection)
        self.assertEqual([item["id"] for item in linked], [source["id"]])
        corrections = get_fact_corrections(
            fact_id,
            connection=self.connection,
        )
        self.assertEqual(len(corrections), 2)
        self.assertEqual(
            corrections[1]["before_values"],
            {"valid_from": "2025-01-01", "valid_to": None},
        )

    def test_correct_fact_can_clear_a_date(self):
        fact_id = add_fact(
            self.person_id,
            "project",
            "role",
            "Synthetic Role",
            valid_from="2025-01-01",
            valid_to="2025-12-31",
            connection=self.connection,
        )

        result = correct_fact(
            fact_id,
            valid_to=None,
            correction_note="Incorrect end date removed",
            connection=self.connection,
        )

        self.assertIsNone(result["fact"]["valid_to"])
        self.assertEqual(
            result["correction"]["after_values"],
            {"valid_to": None},
        )

    def test_invalid_correction_rolls_back_fact_and_audit(self):
        fact_id = add_fact(
            self.person_id,
            "project",
            "role",
            "Synthetic Role",
            valid_from="2025-01-01",
            connection=self.connection,
        )

        with self.assertRaises(FactValidationError):
            correct_fact(
                fact_id,
                valid_from="2026-01-01",
                valid_to="2025-01-01",
                correction_note="Invalid correction",
                connection=self.connection,
            )

        stored = get_fact(fact_id, connection=self.connection)
        self.assertEqual(stored["valid_from"], "2025-01-01")
        self.assertIsNone(stored["valid_to"])
        self.assertEqual(
            get_fact_corrections(fact_id, connection=self.connection),
            [],
        )

    def test_correction_requires_change_and_note(self):
        fact_id = add_fact(
            self.person_id,
            "profile",
            "role",
            "Synthetic Role",
            connection=self.connection,
        )

        with self.assertRaises(FactValidationError):
            correct_fact(
                fact_id,
                value="Synthetic Role",
                correction_note="No change",
                connection=self.connection,
            )
        with self.assertRaises(FactValidationError):
            correct_fact(
                fact_id,
                value="Changed Role",
                correction_note="",
                connection=self.connection,
            )

    def test_supersede_fact_closes_old_record_and_inherits_metadata(self):
        old_id = add_fact(
            self.person_id,
            "education",
            "class",
            "3",
            valid_from="2025-09-01",
            visibility="private",
            confidence=0.8,
            connection=self.connection,
        )

        new_fact = supersede_fact(
            old_id,
            "4",
            valid_from="2026-09-01",
            connection=self.connection,
        )
        old_fact = get_fact(old_id, connection=self.connection)

        self.assertEqual(old_fact["valid_to"], "2026-08-31")
        self.assertEqual(new_fact["value"], "4")
        self.assertEqual(new_fact["visibility"], "private")
        self.assertEqual(new_fact["confidence"], 0.8)
        self.assertEqual(
            get_current_fact(
                self.person_id,
                "education",
                "class",
                as_of="2026-09-01",
                connection=self.connection,
            )["id"],
            new_fact["id"],
        )

    def test_supersede_fact_can_leave_an_explicit_gap(self):
        old_id = add_fact(
            self.person_id,
            "education",
            "class",
            "3",
            valid_from="2025-09-01",
            connection=self.connection,
        )

        supersede_fact(
            old_id,
            "4",
            valid_from="2026-09-01",
            previous_valid_to="2026-06-30",
            connection=self.connection,
        )

        gap = get_current_fact(
            self.person_id,
            "education",
            "class",
            as_of="2026-07-15",
            connection=self.connection,
        )
        self.assertIsNone(gap)

    def test_supersede_fact_links_selected_source_atomically(self):
        old_id = add_fact(
            self.person_id,
            "profile",
            "role",
            "Old Synthetic Role",
            valid_from="2025-01-01",
            connection=self.connection,
        )
        source = add_source(
            "manual",
            "Synthetic correction",
            connection=self.connection,
        )

        new_fact = supersede_fact(
            old_id,
            "New Synthetic Role",
            valid_from="2026-01-01",
            source_id=source["id"],
            connection=self.connection,
        )

        linked = get_sources_for_fact(
            new_fact["id"],
            connection=self.connection,
        )
        self.assertEqual([item["id"] for item in linked], [source["id"]])

    def test_supersede_rolls_back_when_source_is_unknown(self):
        old_id = add_fact(
            self.person_id,
            "profile",
            "role",
            "Synthetic Role",
            valid_from="2025-01-01",
            connection=self.connection,
        )

        with self.assertRaises(LinkSourceNotFoundError):
            supersede_fact(
                old_id,
                "Changed Role",
                valid_from="2026-01-01",
                source_id=999,
                connection=self.connection,
            )

        self.assertIsNone(
            get_fact(old_id, connection=self.connection)["valid_to"]
        )

    def test_supersede_fact_rolls_back_when_successor_conflicts(self):
        old_id = add_fact(
            self.person_id,
            "education",
            "class",
            "3",
            valid_from="2025-09-01",
            connection=self.connection,
        )
        add_fact(
            self.person_id,
            "education",
            "class",
            "Conflicting Value",
            valid_from="2026-09-01",
            allow_overlap=True,
            connection=self.connection,
        )

        with self.assertRaises(OverlappingFactError):
            supersede_fact(
                old_id,
                "4",
                valid_from="2026-09-01",
                connection=self.connection,
            )

        self.assertIsNone(
            get_fact(old_id, connection=self.connection)["valid_to"],
            "Başarısız successor ekleme eski fact'i kapatmamalıdır.",
        )


if __name__ == "__main__":
    unittest.main()
