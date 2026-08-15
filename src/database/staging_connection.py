import sqlite3
from pathlib import Path

from src.database.connection import DATABASE_PATH, PROJECT_ROOT
from src.database.migrations import (
    STAGING_MIGRATIONS_DIR,
    apply_migrations,
)


STAGING_DATABASE_PATH = (
    PROJECT_ROOT / "data" / "staging" / "candidates" / "candidates.db"
)
STAGING_SCHEMA_PATH = PROJECT_ROOT / "src" / "database" / "staging_schema.sql"


def get_staging_connection(
    database_path: str | Path | None = None,
) -> sqlite3.Connection:
    path = Path(database_path) if database_path is not None else STAGING_DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_staging_database(
    database_path: str | Path | None = None,
    *,
    migrations_dir: str | Path | None = None,
) -> Path:
    path = Path(database_path) if database_path is not None else STAGING_DATABASE_PATH
    connection = get_staging_connection(path)
    try:
        apply_migrations(
            connection,
            migrations_dir or STAGING_MIGRATIONS_DIR,
        )
    finally:
        connection.close()
    return path


def attach_core_database(
    connection: sqlite3.Connection,
    database_path: str | Path | None = None,
) -> None:
    """Attach the core DB once under the stable SQLite alias 'core'."""

    attached_names = {
        row[1] for row in connection.execute("PRAGMA database_list").fetchall()
    }
    if "core" in attached_names:
        return

    path = Path(database_path) if database_path is not None else DATABASE_PATH
    connection.execute("ATTACH DATABASE ? AS core", (str(path.resolve()),))
