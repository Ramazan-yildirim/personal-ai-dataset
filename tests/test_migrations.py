import sqlite3
import tempfile
import unittest
from pathlib import Path


from src.database.connection import get_connection
from src.database.migrations import (
    CORE_MIGRATIONS_DIR,
    MigrationStateError,
    MigrationValidationError,
    apply_migrations,
    initialize_core_database,
)
from src.database.staging_connection import initialize_staging_database


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "database" / "schema.sql"


class MigrationsTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_initializes_core_database_idempotently(self):
        database_path = self.root / "core" / "personal_data.db"

        path, first = initialize_core_database(database_path)
        _, second = initialize_core_database(database_path)

        self.assertEqual(path, database_path)
        self.assertEqual([migration.version for migration in first], [1, 2])
        self.assertEqual(second, [])
        connection = get_connection(database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertIn("facts", tables)
            self.assertIn("fact_corrections", tables)
            self.assertIn("schema_migrations", tables)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_keys").fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_baselines_legacy_schema_without_losing_data(self):
        database_path = self.root / "legacy.db"
        connection = get_connection(database_path)
        try:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO persons (name) VALUES (?)",
                ("Example User",),
            )
            connection.commit()
        finally:
            connection.close()

        _, applied = initialize_core_database(database_path)

        self.assertEqual(
            [migration.version for migration in applied],
            [1, 2],
        )
        connection = get_connection(database_path)
        try:
            name = connection.execute(
                "SELECT name FROM persons"
            ).fetchone()[0]
            self.assertEqual(name, "Example User")
        finally:
            connection.close()

    def test_initializes_staging_database_with_history(self):
        database_path = self.root / "staging" / "candidates.db"

        initialize_staging_database(database_path)
        initialize_staging_database(database_path)

        connection = sqlite3.connect(database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertIn("fact_candidates", tables)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_rejects_modified_applied_migration(self):
        migrations_dir = self.root / "migrations"
        migrations_dir.mkdir()
        migration_path = migrations_dir / "001_initial.sql"
        migration_path.write_text(
            "CREATE TABLE example (id INTEGER PRIMARY KEY);",
            encoding="utf-8",
        )
        connection = sqlite3.connect(":memory:")
        try:
            apply_migrations(connection, migrations_dir)
            migration_path.write_text(
                "CREATE TABLE changed (id INTEGER PRIMARY KEY);",
                encoding="utf-8",
            )

            with self.assertRaises(MigrationStateError):
                apply_migrations(connection, migrations_dir)
        finally:
            connection.close()

    def test_checksum_ignores_platform_line_endings(self):
        migrations_dir = self.root / "migrations"
        migrations_dir.mkdir()
        migration_path = migrations_dir / "001_initial.sql"
        migration_path.write_bytes(
            b"CREATE TABLE example (\r\n"
            b"    id INTEGER PRIMARY KEY\r\n"
            b");\r\n"
        )
        connection = sqlite3.connect(":memory:")
        try:
            apply_migrations(connection, migrations_dir)
            migration_path.write_bytes(
                b"CREATE TABLE example (\n"
                b"    id INTEGER PRIMARY KEY\n"
                b");\n"
            )

            self.assertEqual(
                apply_migrations(connection, migrations_dir),
                [],
            )
        finally:
            connection.close()

    def test_failed_migration_rolls_back_schema_and_history(self):
        migrations_dir = self.root / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_initial.sql").write_text(
            "CREATE TABLE stable (id INTEGER PRIMARY KEY);",
            encoding="utf-8",
        )
        connection = sqlite3.connect(":memory:")
        try:
            apply_migrations(connection, migrations_dir)
            (migrations_dir / "002_broken.sql").write_text(
                "CREATE TABLE transient (id INTEGER); INVALID SQL;",
                encoding="utf-8",
            )

            with self.assertRaises(sqlite3.Error):
                apply_migrations(connection, migrations_dir)

            transient = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'transient'
                """
            ).fetchone()
            self.assertIsNone(transient)
            self.assertEqual(
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_rejects_version_gaps_and_active_transactions(self):
        migrations_dir = self.root / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "002_second.sql").write_text(
            "SELECT 1;",
            encoding="utf-8",
        )
        connection = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(MigrationValidationError):
                apply_migrations(connection, migrations_dir)

            connection.execute("BEGIN")
            with self.assertRaises(MigrationStateError):
                apply_migrations(connection, CORE_MIGRATIONS_DIR)
            connection.rollback()
        finally:
            connection.close()

    def test_rejects_gaps_in_applied_history(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum)
                VALUES (2, 'missing_first', 'synthetic')
                """
            )
            connection.commit()

            with self.assertRaises(MigrationStateError):
                apply_migrations(connection, CORE_MIGRATIONS_DIR)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
