"""Numbered, checksum-protected SQLite schema migrations."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.database.connection import (
    DATABASE_PATH,
    PROJECT_ROOT,
    get_connection,
)


CORE_MIGRATIONS_DIR = PROJECT_ROOT / "src" / "database" / "migrations" / "core"
STAGING_MIGRATIONS_DIR = (
    PROJECT_ROOT / "src" / "database" / "migrations" / "staging"
)
MIGRATION_FILE_PATTERN = re.compile(
    r"(?P<version>\d{3,})_(?P<name>[a-z0-9][a-z0-9_]*)\.sql"
)


class MigrationError(Exception):
    """Base exception for migration discovery and execution."""


class MigrationValidationError(MigrationError, ValueError):
    """Raised when local migration files are invalid."""


class MigrationStateError(MigrationError):
    """Raised when database migration history is inconsistent."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


def _read_migration(path: Path) -> tuple[str, str]:
    try:
        sql = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise MigrationValidationError(
            f"Migration must be UTF-8: {path.name}"
        ) from error
    normalized_sql = sql.replace("\r\n", "\n").replace("\r", "\n")
    checksum = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
    return normalized_sql, checksum


def discover_migrations(
    migrations_dir: str | Path,
) -> list[Migration]:
    """Return validated migrations in strict version order."""

    directory = Path(migrations_dir).resolve()
    if not directory.exists() or not directory.is_dir():
        raise MigrationValidationError(
            f"Migration directory not found: {directory}"
        )

    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_FILE_PATTERN.fullmatch(path.name)
        if match is None:
            raise MigrationValidationError(
                f"Invalid migration filename: {path.name}"
            )
        _, checksum = _read_migration(path)
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                path=path,
                checksum=checksum,
            )
        )

    if not migrations:
        raise MigrationValidationError(
            f"No migration files found: {directory}"
        )

    versions = [migration.version for migration in migrations]
    expected_versions = list(range(1, len(migrations) + 1))
    if versions != expected_versions:
        raise MigrationValidationError(
            "Migration versions must be unique, contiguous, and start at 001."
        )
    return migrations


def _ensure_history_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()


def _applied_history(
    connection: sqlite3.Connection,
) -> dict[int, tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT version, name, checksum
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()
    return {
        int(row[0]): (str(row[1]), str(row[2]))
        for row in rows
    }


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path,
) -> list[Migration]:
    """Apply pending migrations atomically and verify applied checksums."""

    if connection.in_transaction:
        raise MigrationStateError(
            "Migrations require a connection without an active transaction."
        )

    migrations = discover_migrations(migrations_dir)
    _ensure_history_table(connection)
    applied_history = _applied_history(connection)
    local_by_version = {
        migration.version: migration for migration in migrations
    }
    applied_versions = sorted(applied_history)
    expected_applied = list(range(1, len(applied_versions) + 1))
    if applied_versions != expected_applied:
        raise MigrationStateError(
            "Applied migration history must be a contiguous prefix."
        )

    for version, (name, checksum) in applied_history.items():
        local = local_by_version.get(version)
        if local is None:
            raise MigrationStateError(
                f"Applied migration {version:03d} is missing locally."
            )
        if local.name != name or local.checksum != checksum:
            raise MigrationStateError(
                f"Applied migration {version:03d} was modified."
            )

    applied_now = []
    for migration in migrations:
        if migration.version in applied_history:
            continue

        sql, _ = _read_migration(migration.path)
        try:
            connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\n")
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.name, migration.checksum),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        applied_now.append(migration)

    return applied_now


def initialize_core_database(
    database_path: str | Path | None = None,
    *,
    migrations_dir: str | Path | None = None,
) -> tuple[Path, list[Migration]]:
    """Open, migrate, and close the core database."""

    path = Path(database_path) if database_path is not None else DATABASE_PATH
    directory = (
        Path(migrations_dir)
        if migrations_dir is not None
        else CORE_MIGRATIONS_DIR
    )
    connection = get_connection(path)
    try:
        applied = apply_migrations(connection, directory)
    finally:
        connection.close()
    return path, applied
