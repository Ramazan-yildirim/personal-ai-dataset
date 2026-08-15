"""Reusable operations for creating and querying personal facts."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from src.database.connection import get_connection
from src.database.fact_sources import link_fact_source
from src.database.persons import PersonNotFoundError as PersonServiceNotFoundError


ALLOWED_VISIBILITIES = {"public", "private", "internal"}
ALLOWED_STATUSES = {"active", "deprecated", "deleted"}
UNCHANGED = object()


class FactError(Exception):
    """Base exception for fact operations."""


class FactValidationError(FactError, ValueError):
    """Raised when fact input is invalid."""


class PersonNotFoundError(FactError, PersonServiceNotFoundError):
    """Raised when a fact references a person that does not exist."""


class FactNotFoundError(FactError):
    """Raised when a requested fact does not exist."""


class FactStateError(FactError):
    """Raised when an operation is invalid for the fact's current state."""


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


def _validate_fact_id(fact_id: int) -> None:
    if isinstance(fact_id, bool) or not isinstance(fact_id, int) or fact_id <= 0:
        raise FactValidationError("fact_id pozitif bir tam sayı olmalıdır.")


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


def _get_fact_row(connection: sqlite3.Connection, fact_id: int) -> sqlite3.Row:
    fact = connection.execute(
        "SELECT * FROM facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    if fact is None:
        raise FactNotFoundError(f"fact_id={fact_id} için fact bulunamadı.")
    return fact


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
    exclude_fact_id: int | None = None,
) -> sqlite3.Row | None:
    query = """
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
    """
    parameters: list[Any] = [
        person_id,
        category,
        key,
        value,
        valid_from,
        valid_to,
        visibility,
        status,
        confidence,
    ]
    if exclude_fact_id is not None:
        query += " AND id != ?"
        parameters.append(exclude_fact_id)
    query += " LIMIT 1"
    return connection.execute(query, parameters).fetchone()


def _find_active_overlap(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    category: str,
    key: str,
    valid_from: str | None,
    valid_to: str | None,
    exclude_fact_id: int | None = None,
) -> sqlite3.Row | None:
    query = """
        SELECT id, value, valid_from, valid_to
        FROM facts
        WHERE person_id = ?
          AND category = ?
          AND key = ?
          AND status = 'active'
          AND (valid_to IS NULL OR ? IS NULL OR valid_to >= ?)
          AND (? IS NULL OR valid_from IS NULL OR valid_from <= ?)
    """
    parameters: list[Any] = [
        person_id,
        category,
        key,
        valid_from,
        valid_from,
        valid_to,
        valid_to,
    ]
    if exclude_fact_id is not None:
        query += " AND id != ?"
        parameters.append(exclude_fact_id)
    query += " ORDER BY id LIMIT 1"
    return connection.execute(query, parameters).fetchone()


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


def get_current_facts(
    person_id: int,
    category: str,
    key: str,
    *,
    as_of: str | date | None = None,
    visibility: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return all active facts valid on as_of (today by default)."""

    _validate_person_id(person_id)
    normalized_category = _required_text(category, "category")
    normalized_key = _required_text(key, "key")
    normalized_as_of = _optional_date(as_of, "as_of") or date.today().isoformat()
    if visibility is not None and visibility not in ALLOWED_VISIBILITIES:
        allowed = ", ".join(sorted(ALLOWED_VISIBILITIES))
        raise FactValidationError(f"visibility şu değerlerden biri olmalıdır: {allowed}.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _ensure_person_exists(active_connection, person_id)
        query = """
            SELECT *
            FROM facts
            WHERE person_id = ?
              AND category = ?
              AND key = ?
              AND status = 'active'
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to >= ?)
        """
        parameters: list[Any] = [
            person_id,
            normalized_category,
            normalized_key,
            normalized_as_of,
            normalized_as_of,
        ]
        if visibility is not None:
            query += " AND visibility = ?"
            parameters.append(visibility)
        query += " ORDER BY COALESCE(valid_from, '') DESC, created_at DESC, id DESC"

        rows = active_connection.execute(query, parameters).fetchall()
        return [_row_to_dict(row) for row in rows]
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

    facts = get_current_facts(
        person_id,
        category,
        key,
        as_of=as_of,
        connection=connection,
    )
    if not facts:
        return None
    if len(facts) > 1:
        raise AmbiguousFactError(
            "Tekil sorgu birden fazla geçerli fact buldu. "
            "Çok değerli key için get_current_facts() kullanın."
        )
    return facts[0]


def list_facts(
    person_id: int,
    *,
    include_inactive: bool = False,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List a person's facts, optionally including audit-only statuses."""

    _validate_person_id(person_id)
    if not isinstance(include_inactive, bool):
        raise FactValidationError("include_inactive boolean olmalıdır.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _ensure_person_exists(active_connection, person_id)
        query = "SELECT * FROM facts WHERE person_id = ?"
        if not include_inactive:
            query += " AND status = 'active'"
        query += """
            ORDER BY
                category,
                key,
                COALESCE(valid_from, ''),
                id
        """
        rows = active_connection.execute(query, (person_id,)).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()


def correct_fact(
    fact_id: int,
    *,
    category: Any = UNCHANGED,
    key: Any = UNCHANGED,
    value: Any = UNCHANGED,
    valid_from: Any = UNCHANGED,
    valid_to: Any = UNCHANGED,
    visibility: Any = UNCHANGED,
    confidence: Any = UNCHANGED,
    correction_note: str,
    allow_overlap: bool = False,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Correct selected fields in place and write an immutable audit record."""

    _validate_fact_id(fact_id)
    if not isinstance(correction_note, str) or not correction_note.strip():
        raise FactValidationError("Düzeltme için correction_note zorunludur.")
    if not isinstance(allow_overlap, bool):
        raise FactValidationError("allow_overlap boolean olmalıdır.")

    active_connection, owns_connection = _connection_or_default(connection)
    savepoint_name = "correct_fact"
    try:
        stored = _get_fact_row(active_connection, fact_id)
        if stored["status"] == "deleted":
            raise FactStateError("Deleted bir fact düzeltilemez.")

        proposed = {
            "category": stored["category"] if category is UNCHANGED else category,
            "key": stored["key"] if key is UNCHANGED else key,
            "value": stored["value"] if value is UNCHANGED else value,
            "valid_from": (
                stored["valid_from"] if valid_from is UNCHANGED else valid_from
            ),
            "valid_to": stored["valid_to"] if valid_to is UNCHANGED else valid_to,
            "visibility": (
                stored["visibility"] if visibility is UNCHANGED else visibility
            ),
            "confidence": (
                stored["confidence"] if confidence is UNCHANGED else confidence
            ),
        }
        (
            normalized_category,
            normalized_key,
            normalized_value,
            normalized_from,
            normalized_to,
            normalized_confidence,
        ) = _validate_fact_input(
            stored["person_id"],
            proposed["category"],
            proposed["key"],
            proposed["value"],
            proposed["valid_from"],
            proposed["valid_to"],
            proposed["visibility"],
            stored["status"],
            proposed["confidence"],
        )
        normalized = {
            "category": normalized_category,
            "key": normalized_key,
            "value": normalized_value,
            "valid_from": normalized_from,
            "valid_to": normalized_to,
            "visibility": proposed["visibility"],
            "confidence": normalized_confidence,
        }

        duplicate = _find_duplicate(
            active_connection,
            person_id=stored["person_id"],
            status=stored["status"],
            exclude_fact_id=fact_id,
            **normalized,
        )
        if duplicate is not None:
            raise DuplicateFactError(
                f"Düzeltme başka bir fact ile aynı sonucu veriyor "
                f"(id={duplicate['id']})."
            )
        if stored["status"] == "active" and not allow_overlap:
            overlap = _find_active_overlap(
                active_connection,
                person_id=stored["person_id"],
                category=normalized_category,
                key=normalized_key,
                valid_from=normalized_from,
                valid_to=normalized_to,
                exclude_fact_id=fact_id,
            )
            if overlap is not None:
                raise OverlappingFactError(
                    "Düzeltme başka bir aktif fact dönemiyle çakışıyor "
                    f"(fact_id={overlap['id']})."
                )

        changed_fields = [
            field_name
            for field_name, new_value in normalized.items()
            if stored[field_name] != new_value
        ]
        if not changed_fields:
            raise FactValidationError("Düzeltilecek bir alan değişmedi.")
        before_values = {
            field_name: stored[field_name] for field_name in changed_fields
        }
        after_values = {
            field_name: normalized[field_name] for field_name in changed_fields
        }

        active_connection.execute(f"SAVEPOINT {savepoint_name}")
        try:
            active_connection.execute(
                """
                UPDATE facts
                SET category = ?,
                    key = ?,
                    value = ?,
                    valid_from = ?,
                    valid_to = ?,
                    visibility = ?,
                    confidence = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    normalized_category,
                    normalized_key,
                    normalized_value,
                    normalized_from,
                    normalized_to,
                    normalized["visibility"],
                    normalized_confidence,
                    fact_id,
                ),
            )
            cursor = active_connection.execute(
                """
                INSERT INTO fact_corrections (
                    fact_id,
                    changed_fields,
                    before_values,
                    after_values,
                    correction_note
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    json.dumps(changed_fields, ensure_ascii=False),
                    json.dumps(before_values, ensure_ascii=False, sort_keys=True),
                    json.dumps(after_values, ensure_ascii=False, sort_keys=True),
                    correction_note.strip(),
                ),
            )
        except Exception:
            active_connection.execute(
                f"ROLLBACK TO SAVEPOINT {savepoint_name}"
            )
            active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            raise
        else:
            active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            if owns_connection:
                active_connection.commit()

        correction = active_connection.execute(
            "SELECT * FROM fact_corrections WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return {
            "fact": _row_to_dict(_get_fact_row(active_connection, fact_id)),
            "correction": _correction_to_dict(correction),
        }
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def _correction_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    correction = _row_to_dict(row)
    for field_name in ("changed_fields", "before_values", "after_values"):
        correction[field_name] = json.loads(correction[field_name])
    return correction


def get_fact_corrections(
    fact_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return correction audit records for one fact."""

    _validate_fact_id(fact_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        _get_fact_row(active_connection, fact_id)
        rows = active_connection.execute(
            """
            SELECT *
            FROM fact_corrections
            WHERE fact_id = ?
            ORDER BY id
            """,
            (fact_id,),
        ).fetchall()
        return [_correction_to_dict(row) for row in rows]
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


def get_fact(
    fact_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return a fact by id, regardless of status."""

    _validate_fact_id(fact_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        return _row_to_dict(_get_fact_row(active_connection, fact_id))
    finally:
        if owns_connection:
            active_connection.close()


def close_fact(
    fact_id: int,
    valid_to: str | date,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Close or shorten an active fact's inclusive validity period."""

    _validate_fact_id(fact_id)
    normalized_to = _optional_date(valid_to, "valid_to")
    if normalized_to is None:
        raise FactValidationError("valid_to zorunludur.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        fact = _get_fact_row(active_connection, fact_id)
        if fact["status"] != "active":
            raise FactStateError("Yalnızca active bir fact'in dönemi kapatılabilir.")
        if fact["valid_from"] and normalized_to < fact["valid_from"]:
            raise FactValidationError("valid_to, fact'in valid_from tarihinden önce olamaz.")
        if fact["valid_to"] and normalized_to > fact["valid_to"]:
            raise FactValidationError(
                "close_fact mevcut dönemi uzatamaz; yalnızca kapatabilir veya kısaltabilir."
            )

        if fact["valid_to"] != normalized_to:
            active_connection.execute(
                """
                UPDATE facts
                SET valid_to = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_to, fact_id),
            )
            if owns_connection:
                active_connection.commit()

        return _row_to_dict(_get_fact_row(active_connection, fact_id))
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def _set_fact_status(
    fact_id: int,
    target_status: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    _validate_fact_id(fact_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        fact = _get_fact_row(active_connection, fact_id)
        if fact["status"] == target_status:
            return _row_to_dict(fact)
        if fact["status"] == "deleted":
            raise FactStateError("Deleted bir fact'in durumu değiştirilemez.")

        active_connection.execute(
            """
            UPDATE facts
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_status, fact_id),
        )
        if owns_connection:
            active_connection.commit()
        return _row_to_dict(_get_fact_row(active_connection, fact_id))
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def deprecate_fact(
    fact_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Mark a fact as unreliable while preserving its history."""

    return _set_fact_status(fact_id, "deprecated", connection=connection)


def soft_delete_fact(
    fact_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Logically delete a fact without physically removing it."""

    return _set_fact_status(fact_id, "deleted", connection=connection)


def supersede_fact(
    fact_id: int,
    new_value: str,
    *,
    valid_from: str | date,
    previous_valid_to: str | date | None = None,
    visibility: str | None = None,
    confidence: float | None = None,
    source_id: int | None = None,
    allow_overlap: bool = False,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Close an open-ended fact and add its successor atomically.

    By default the previous fact ends one day before the successor starts.
    Pass previous_valid_to explicitly when the history should contain a gap.
    """

    _validate_fact_id(fact_id)
    normalized_value = _required_text(new_value, "new_value")
    normalized_from = _optional_date(valid_from, "valid_from")
    if normalized_from is None:
        raise FactValidationError("valid_from zorunludur.")

    if previous_valid_to is None:
        try:
            normalized_previous_to = (
                date.fromisoformat(normalized_from) - timedelta(days=1)
            ).isoformat()
        except OverflowError as error:
            raise FactValidationError(
                "valid_from için önceki bir kapanış tarihi hesaplanamıyor."
            ) from error
    else:
        normalized_previous_to = _optional_date(
            previous_valid_to,
            "previous_valid_to",
        )

    if normalized_previous_to is None or normalized_previous_to >= normalized_from:
        raise FactValidationError(
            "previous_valid_to, yeni fact'in valid_from tarihinden önce olmalıdır."
        )

    active_connection, owns_connection = _connection_or_default(connection)
    savepoint_name = "supersede_fact"
    try:
        previous_fact = _get_fact_row(active_connection, fact_id)
        if previous_fact["status"] != "active":
            raise FactStateError("Yalnızca active bir fact değiştirilebilir.")
        if previous_fact["valid_to"] is not None:
            raise FactStateError(
                "supersede_fact yalnızca açık uçlu bir fact için kullanılabilir."
            )

        target_visibility = (
            previous_fact["visibility"] if visibility is None else visibility
        )
        target_confidence = (
            previous_fact["confidence"] if confidence is None else confidence
        )

        active_connection.execute(f"SAVEPOINT {savepoint_name}")
        try:
            close_fact(
                fact_id,
                normalized_previous_to,
                connection=active_connection,
            )
            new_fact_id = add_fact(
                previous_fact["person_id"],
                previous_fact["category"],
                previous_fact["key"],
                normalized_value,
                valid_from=normalized_from,
                visibility=target_visibility,
                confidence=target_confidence,
                allow_overlap=allow_overlap,
                connection=active_connection,
            )
            if source_id is not None:
                link_fact_source(
                    new_fact_id,
                    source_id,
                    connection=active_connection,
                )
        except Exception:
            active_connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            raise
        else:
            active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            if owns_connection:
                active_connection.commit()

        return _row_to_dict(_get_fact_row(active_connection, new_fact_id))
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()
