"""Many-to-many provenance links between facts and sources."""

from __future__ import annotations

import sqlite3
from typing import Any

from src.database.connection import get_connection


class FactSourceError(Exception):
    """Base exception for fact-source link operations."""


class FactSourceValidationError(FactSourceError, ValueError):
    """Raised when a link identifier is invalid."""


class LinkFactNotFoundError(FactSourceError):
    """Raised when the fact side of a link does not exist."""


class LinkSourceNotFoundError(FactSourceError):
    """Raised when the source side of a link does not exist."""


class InactiveSourceError(FactSourceError):
    """Raised when a new link targets an inactive source."""


class DeletedFactError(FactSourceError):
    """Raised when a new link targets a logically deleted fact."""


class DuplicateFactSourceError(FactSourceError):
    """Raised when the fact-source relation already exists."""


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


def _validate_id(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FactSourceValidationError(
            f"{field_name} pozitif bir tam sayı olmalıdır."
        )


def _get_fact_row(connection: sqlite3.Connection, fact_id: int) -> sqlite3.Row:
    fact = connection.execute(
        "SELECT * FROM facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    if fact is None:
        raise LinkFactNotFoundError(f"fact_id={fact_id} için fact bulunamadı.")
    return fact


def _get_source_row(
    connection: sqlite3.Connection,
    source_id: int,
) -> sqlite3.Row:
    source = connection.execute(
        "SELECT * FROM sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    if source is None:
        raise LinkSourceNotFoundError(
            f"source_id={source_id} için kaynak bulunamadı."
        )
    return source


def link_fact_source(
    fact_id: int,
    source_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Link a non-deleted fact to an active source."""

    _validate_id(fact_id, "fact_id")
    _validate_id(source_id, "source_id")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        fact = _get_fact_row(active_connection, fact_id)
        source = _get_source_row(active_connection, source_id)
        if fact["status"] == "deleted":
            raise DeletedFactError("Deleted bir fact yeni bir kaynağa bağlanamaz.")
        if not source["is_active"]:
            raise InactiveSourceError("Fact yalnızca active bir kaynağa bağlanabilir.")

        existing = active_connection.execute(
            """
            SELECT 1
            FROM fact_sources
            WHERE fact_id = ? AND source_id = ?
            """,
            (fact_id, source_id),
        ).fetchone()
        if existing is not None:
            raise DuplicateFactSourceError(
                "Bu fact-source bağlantısı zaten mevcut."
            )

        active_connection.execute(
            "INSERT INTO fact_sources (fact_id, source_id) VALUES (?, ?)",
            (fact_id, source_id),
        )
        if owns_connection:
            active_connection.commit()
        return {"fact_id": fact_id, "source_id": source_id}
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def get_sources_for_fact(
    fact_id: int,
    *,
    active_only: bool = False,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return every source linked to a fact."""

    _validate_id(fact_id, "fact_id")
    if not isinstance(active_only, bool):
        raise FactSourceValidationError("active_only boolean olmalıdır.")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _get_fact_row(active_connection, fact_id)
        query = """
            SELECT sources.*
            FROM sources
            JOIN fact_sources ON fact_sources.source_id = sources.id
            WHERE fact_sources.fact_id = ?
        """
        if active_only:
            query += " AND sources.is_active = 1"
        query += " ORDER BY sources.id"
        rows = active_connection.execute(query, (fact_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()


def get_facts_for_source(
    source_id: int,
    *,
    active_only: bool = False,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return every fact linked to a source."""

    _validate_id(source_id, "source_id")
    if not isinstance(active_only, bool):
        raise FactSourceValidationError("active_only boolean olmalıdır.")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _get_source_row(active_connection, source_id)
        query = """
            SELECT facts.*
            FROM facts
            JOIN fact_sources ON fact_sources.fact_id = facts.id
            WHERE fact_sources.source_id = ?
        """
        if active_only:
            query += " AND facts.status = 'active'"
        query += " ORDER BY facts.id"
        rows = active_connection.execute(query, (source_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()
