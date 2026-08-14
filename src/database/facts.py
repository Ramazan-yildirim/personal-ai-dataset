"""Reusable operations for creating and querying personal facts."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from src.database.connection import get_connection


ALLOWED_VISIBILITIES = {"public", "private", "internal"}
ALLOWED_STATUSES = {"active", "deprecated", "deleted"}


class FactError(Exception):
    """Base exception for fact operations."""


class FactValidationError(FactError, ValueError):
    """Raised when fact input is invalid."""


class PersonNotFoundError(FactError):
    """Raised when a fact references a person that does not exist."""


class DuplicateFactError(FactError):
    """Raised when an identical fact already exists."""


class OverlappingFactError(FactError):
    """Raised when a single-value fact conflicts with an active period."""


class AmbiguousFactError(FactError):
    """Raised when a singular lookup finds multiple valid facts."""


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactValidationError(f"{field_name} boş olmayan bir metin olmalıdır.")
    return value.strip()


def _optional_date(value: str | date | None, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise FactValidationError(f"{field_name}, YYYY-MM-DD biçiminde olmalıdır.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise FactValidationError(
            f"{field_name}, YYYY-MM-DD biçiminde geçerli bir tarih olmalıdır."
        ) from error


def _validate_person_id(person_id: int) -> None:
    if isinstance(person_id, bool) or not isinstance(person_id, int) or person_id <= 0:
        raise FactValidationError("person_id pozitif bir tam sayı olmalıdır.")


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


def _validate_fact_input(
    person_id: int,
    category: str,
    key: str,
    value: str,
    valid_from: str | date | None,
    valid_to: str | date | None,
    visibility: str,
    status: str,
    confidence: float,
) -> tuple[str, str, str, str | None, str | None, float]:
    _validate_person_id(person_id)
    normalized_category = _required_text(category, "category")
    normalized_key = _required_text(key, "key")
    normalized_value = _required_text(value, "value")
    normalized_from = _optional_date(valid_from, "valid_from")
    normalized_to = _optional_date(valid_to, "valid_to")

    if normalized_from and normalized_to and normalized_from > normalized_to:
        raise FactValidationError("valid_from, valid_to tarihinden sonra olamaz.")
    if visibility not in ALLOWED_VISIBILITIES:
        allowed = ", ".join(sorted(ALLOWED_VISIBILITIES))
        raise FactValidationError(f"visibility şu değerlerden biri olmalıdır: {allowed}.")
    if status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise FactValidationError(f"status şu değerlerden biri olmalıdır: {allowed}.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise FactValidationError("confidence sayısal olmalıdır.")

    normalized_confidence = float(confidence)
    if not 0.0 <= normalized_confidence <= 1.0:
        raise FactValidationError("confidence 0 ile 1 arasında olmalıdır.")

    return (
        normalized_category,
        normalized_key,
        normalized_value,
        normalized_from,
        normalized_to,
        normalized_confidence,
    )


def _ensure_person_exists(connection: sqlite3.Connection, person_id: int) -> None:
    person = connection.execute(
        "SELECT 1 FROM persons WHERE id = ?",
        (person_id,),
    ).fetchone()
    if person is None:
        raise PersonNotFoundError(f"person_id={person_id} için kişi bulunamadı.")


def _find_duplicate(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    category: str,
    key: str,
    value: str,
    valid_from: str | None,
    valid_to: str | None,
    visibility: str,
    status: str,
    confidence: float,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id
        FROM facts
        WHERE person_id = ?
          AND category = ?
          AND key = ?
          AND value = ?
          AND valid_from IS ?
          AND valid_to IS ?
          AND visibility = ?
          AND status = ?
          AND confidence = ?
        LIMIT 1
        """,
        (
            person_id,
            category,
            key,
            value,
            valid_from,
            valid_to,
            visibility,
            status,
            confidence,
        ),
    ).fetchone()


def _find_active_overlap(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    category: str,
    key: str,
    valid_from: str | None,
    valid_to: str | None,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, value, valid_from, valid_to
        FROM facts
        WHERE person_id = ?
          AND category = ?
          AND key = ?
          AND status = 'active'
          AND (valid_to IS NULL OR ? IS NULL OR valid_to >= ?)
          AND (? IS NULL OR valid_from IS NULL OR valid_from <= ?)
        ORDER BY id
        LIMIT 1
        """,
        (
            person_id,
            category,
            key,
            valid_from,
            valid_from,
            valid_to,
            valid_to,
        ),
    ).fetchone()


def add_fact(
    person_id: int,
    category: str,
    key: str,
    value: str,
    *,
    valid_from: str | date | None = None,
    valid_to: str | date | None = None,
    visibility: str = "public",
    status: str = "active",
    confidence: float = 1.0,
    allow_overlap: bool = False,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Validate and insert a fact, returning its database id.

    Active periods for the same person/category/key are treated as single-value
    facts by default. Set allow_overlap=True only for intentionally multi-value
    keys, such as multiple programming languages.
    """

    (
        normalized_category,
        normalized_key,
        normalized_value,
        normalized_from,
        normalized_to,
        normalized_confidence,
    ) = _validate_fact_input(
        person_id,
        category,
        key,
        value,
        valid_from,
        valid_to,
        visibility,
        status,
        confidence,
    )
    if not isinstance(allow_overlap, bool):
        raise FactValidationError("allow_overlap boolean olmalıdır.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _ensure_person_exists(active_connection, person_id)
        duplicate = _find_duplicate(
            active_connection,
            person_id=person_id,
            category=normalized_category,
            key=normalized_key,
            value=normalized_value,
            valid_from=normalized_from,
            valid_to=normalized_to,
            visibility=visibility,
            status=status,
            confidence=normalized_confidence,
        )
        if duplicate is not None:
            raise DuplicateFactError(
                f"Aynı fact zaten mevcut (id={duplicate['id']})."
            )

        if status == "active" and not allow_overlap:
            overlap = _find_active_overlap(
                active_connection,
                person_id=person_id,
                category=normalized_category,
                key=normalized_key,
                valid_from=normalized_from,
                valid_to=normalized_to,
            )
            if overlap is not None:
                raise OverlappingFactError(
                    "Aynı person/category/key için çakışan aktif dönem var "
                    f"(fact_id={overlap['id']}, value={overlap['value']!r})."
                )

        cursor = active_connection.execute(
            """
            INSERT INTO facts (
                person_id, category, key, value,
                valid_from, valid_to, visibility, status, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                normalized_category,
                normalized_key,
                normalized_value,
                normalized_from,
                normalized_to,
                visibility,
                status,
                normalized_confidence,
            ),
        )
        if owns_connection:
            active_connection.commit()
        return int(cursor.lastrowid)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def get_current_fact(
    person_id: int,
    category: str,
    key: str,
    *,
    as_of: str | date | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return the single active fact valid on as_of (today by default)."""

    _validate_person_id(person_id)
    normalized_category = _required_text(category, "category")
    normalized_key = _required_text(key, "key")
    normalized_as_of = _optional_date(as_of, "as_of") or date.today().isoformat()

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _ensure_person_exists(active_connection, person_id)
        rows = active_connection.execute(
            """
            SELECT *
            FROM facts
            WHERE person_id = ?
              AND category = ?
              AND key = ?
              AND status = 'active'
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to >= ?)
            ORDER BY COALESCE(valid_from, '') DESC, created_at DESC, id DESC
            LIMIT 2
            """,
            (
                person_id,
                normalized_category,
                normalized_key,
                normalized_as_of,
                normalized_as_of,
            ),
        ).fetchall()

        if not rows:
            return None
        if len(rows) > 1:
            raise AmbiguousFactError(
                "Tekil sorgu birden fazla geçerli fact buldu. "
                "Bu key çok değerliyse çoğul sorgu desteği eklenmelidir."
            )
        return _row_to_dict(rows[0])
    finally:
        if owns_connection:
            active_connection.close()


def get_fact_history(
    person_id: int,
    category: str,
    key: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return all historical records, including deprecated and deleted facts."""

    _validate_person_id(person_id)
    normalized_category = _required_text(category, "category")
    normalized_key = _required_text(key, "key")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _ensure_person_exists(active_connection, person_id)
        rows = active_connection.execute(
            """
            SELECT *
            FROM facts
            WHERE person_id = ?
              AND category = ?
              AND key = ?
            ORDER BY
                CASE WHEN valid_from IS NULL THEN 0 ELSE 1 END,
                valid_from,
                created_at,
                id
            """,
            (person_id, normalized_category, normalized_key),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()
