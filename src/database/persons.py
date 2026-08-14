"""Reusable operations for managing people in the core dataset."""

from __future__ import annotations

import sqlite3
from typing import Any

from src.database.connection import get_connection


class PersonError(Exception):
    """Base exception for person operations."""


class PersonValidationError(PersonError, ValueError):
    """Raised when person input is invalid."""


class PersonNotFoundError(PersonError):
    """Raised when a requested person does not exist."""


class DuplicatePersonError(PersonError):
    """Raised when a person with the same normalized name already exists."""

    def __init__(self, person: dict[str, Any]):
        self.person = person
        super().__init__(
            f"Bu kişi zaten veritabanında kayıtlı (id={person['id']})."
        )


def _connection_or_default(
    connection: sqlite3.Connection | None,
) -> tuple[sqlite3.Connection, bool]:
    owns_connection = connection is None
    active_connection = connection or get_connection()
    active_connection.row_factory = sqlite3.Row
    active_connection.execute("PRAGMA foreign_keys = ON")
    return active_connection, owns_connection


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _normalize_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise PersonValidationError("Kişi adı boş olmayan bir metin olmalıdır.")
    return " ".join(name.split())


def _validate_person_id(person_id: int) -> None:
    if isinstance(person_id, bool) or not isinstance(person_id, int) or person_id <= 0:
        raise PersonValidationError("person_id pozitif bir tam sayı olmalıdır.")


def create_person(
    name: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Create a person and return the stored record."""

    normalized_name = _normalize_name(name)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        existing = active_connection.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM persons
            WHERE name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (normalized_name,),
        ).fetchone()
        if existing is not None:
            raise DuplicatePersonError(_row_to_dict(existing))

        cursor = active_connection.execute(
            "INSERT INTO persons (name) VALUES (?)",
            (normalized_name,),
        )
        if owns_connection:
            active_connection.commit()
        return get_person(cursor.lastrowid, connection=active_connection)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def get_person(
    person_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return a person by id."""

    _validate_person_id(person_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        person = active_connection.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM persons
            WHERE id = ?
            """,
            (person_id,),
        ).fetchone()
        if person is None:
            raise PersonNotFoundError(
                f"person_id={person_id} için kişi bulunamadı."
            )
        return _row_to_dict(person)
    finally:
        if owns_connection:
            active_connection.close()


def list_persons(
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return all people in insertion order."""

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        rows = active_connection.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM persons
            ORDER BY id
            """
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()
