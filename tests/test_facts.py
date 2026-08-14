import sqlite3
import unittest
from pathlib import Path


from src.database.facts import (
    AmbiguousFactError,
    DuplicateFactError,
    FactValidationError,
    OverlappingFactError,
    PersonNotFoundError,
    add_fact,
    get_current_fact,
    get_fact_history,
)


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


if __name__ == "__main__":
    unittest.main()
