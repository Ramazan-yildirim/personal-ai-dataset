import sqlite3
import unittest
from pathlib import Path


from src.database.fact_sources import (
    DeletedFactError,
    DuplicateFactSourceError,
    InactiveSourceError,
    LinkFactNotFoundError,
    LinkSourceNotFoundError,
    get_facts_for_source,
    get_sources_for_fact,
    link_fact_source,
)
from src.database.facts import add_fact, deprecate_fact, soft_delete_fact
from src.database.persons import create_person
from src.database.sources import add_source, deactivate_source


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class FactSourcesTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        person = create_person("Example User", connection=self.connection)
        self.fact_id = add_fact(
            person["id"],
            "education",
            "department",
            "Example Department",
            connection=self.connection,
        )
        source = add_source(
            "manual",
            "Synthetic statement",
            connection=self.connection,
        )
        self.source_id = source["id"]

    def tearDown(self):
        self.connection.close()

    def test_link_and_bidirectional_queries(self):
        link = link_fact_source(
            self.fact_id,
            self.source_id,
            connection=self.connection,
        )

        sources = get_sources_for_fact(
            self.fact_id,
            connection=self.connection,
        )
        facts = get_facts_for_source(
            self.source_id,
            connection=self.connection,
        )

        self.assertEqual(
            link,
            {"fact_id": self.fact_id, "source_id": self.source_id},
        )
        self.assertEqual([source["id"] for source in sources], [self.source_id])
        self.assertEqual([fact["id"] for fact in facts], [self.fact_id])

    def test_duplicate_link_is_rejected(self):
        link_fact_source(
            self.fact_id,
            self.source_id,
            connection=self.connection,
        )

        with self.assertRaises(DuplicateFactSourceError):
            link_fact_source(
                self.fact_id,
                self.source_id,
                connection=self.connection,
            )

    def test_new_link_requires_active_source(self):
        deactivate_source(self.source_id, connection=self.connection)

        with self.assertRaises(InactiveSourceError):
            link_fact_source(
                self.fact_id,
                self.source_id,
                connection=self.connection,
            )

    def test_new_link_rejects_deleted_fact(self):
        soft_delete_fact(self.fact_id, connection=self.connection)

        with self.assertRaises(DeletedFactError):
            link_fact_source(
                self.fact_id,
                self.source_id,
                connection=self.connection,
            )

    def test_historical_links_remain_queryable(self):
        link_fact_source(
            self.fact_id,
            self.source_id,
            connection=self.connection,
        )
        deactivate_source(self.source_id, connection=self.connection)
        deprecate_fact(self.fact_id, connection=self.connection)

        all_sources = get_sources_for_fact(
            self.fact_id,
            connection=self.connection,
        )
        active_sources = get_sources_for_fact(
            self.fact_id,
            active_only=True,
            connection=self.connection,
        )
        all_facts = get_facts_for_source(
            self.source_id,
            connection=self.connection,
        )
        active_facts = get_facts_for_source(
            self.source_id,
            active_only=True,
            connection=self.connection,
        )

        self.assertEqual(len(all_sources), 1)
        self.assertEqual(active_sources, [])
        self.assertEqual(len(all_facts), 1)
        self.assertEqual(active_facts, [])

    def test_unknown_link_sides_raise(self):
        with self.assertRaises(LinkFactNotFoundError):
            link_fact_source(999, self.source_id, connection=self.connection)
        with self.assertRaises(LinkSourceNotFoundError):
            link_fact_source(self.fact_id, 999, connection=self.connection)


if __name__ == "__main__":
    unittest.main()
