import sqlite3
import unittest
from pathlib import Path


from src.database.persons import (
    DuplicatePersonError,
    PersonNotFoundError,
    PersonValidationError,
    create_person,
    get_person,
    list_persons,
)


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class PersonsTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        self.connection.close()

    def test_create_and_get_person_normalizes_whitespace(self):
        created = create_person(
            "  Example   User  ",
            connection=self.connection,
        )
        stored = get_person(created["id"], connection=self.connection)

        self.assertEqual(stored["name"], "Example User")

    def test_duplicate_name_is_case_insensitive(self):
        created = create_person("Example User", connection=self.connection)

        with self.assertRaises(DuplicatePersonError) as context:
            create_person("example user", connection=self.connection)

        self.assertEqual(context.exception.person["id"], created["id"])

    def test_list_persons_returns_in_insertion_order(self):
        create_person("Example One", connection=self.connection)
        create_person("Example Two", connection=self.connection)

        persons = list_persons(connection=self.connection)

        self.assertEqual(
            [person["name"] for person in persons],
            ["Example One", "Example Two"],
        )

    def test_rejects_empty_name_and_invalid_id(self):
        with self.assertRaises(PersonValidationError):
            create_person("   ", connection=self.connection)
        with self.assertRaises(PersonValidationError):
            get_person(0, connection=self.connection)

    def test_unknown_person_raises(self):
        with self.assertRaises(PersonNotFoundError):
            get_person(999, connection=self.connection)


if __name__ == "__main__":
    unittest.main()
