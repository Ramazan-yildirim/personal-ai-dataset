"""Staging candidate validation and manual review workflow."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from src.database.fact_sources import FactSourceError, link_fact_source
from src.database.facts import FactError, add_fact, get_fact
from src.database.staging_connection import (
    attach_core_database,
    get_staging_connection,
)


REVIEW_STATUSES = {"pending", "approved", "rejected"}
VALIDATION_STATUSES = {"pending", "valid", "invalid"}


class CandidateError(Exception):
    """Base exception for candidate workflow operations."""


class CandidateInputError(CandidateError, ValueError):
    """Raised when candidate workflow input is structurally invalid."""


class CandidateNotFoundError(CandidateError):
    """Raised when a requested candidate does not exist."""


class CandidateStateError(CandidateError):
    """Raised when a review operation is invalid for the current state."""


class CandidateValidationFailedError(CandidateError):
    """Raised when an invalid candidate cannot be approved."""

    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("Candidate validasyonu başarısız.")


def _connection_or_default(
    connection: sqlite3.Connection | None,
) -> tuple[sqlite3.Connection, bool]:
    owns_connection = connection is None
    active_connection = connection or get_staging_connection()
    active_connection.row_factory = sqlite3.Row
    active_connection.execute("PRAGMA foreign_keys = ON")
    return active_connection, owns_connection


def _validate_id(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateInputError(f"{field_name} pozitif bir tam sayı olmalıdır.")


def _candidate_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    candidate = {key: row[key] for key in row.keys()}
    try:
        candidate["validation_report"] = json.loads(
            candidate["validation_report"]
        )
    except (TypeError, json.JSONDecodeError):
        candidate["validation_report"] = []
    candidate["allow_overlap"] = bool(candidate["allow_overlap"])
    return candidate


def _get_candidate_row(
    connection: sqlite3.Connection,
    candidate_id: int,
) -> sqlite3.Row:
    candidate = connection.execute(
        "SELECT * FROM fact_candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    if candidate is None:
        raise CandidateNotFoundError(
            f"candidate_id={candidate_id} için candidate bulunamadı."
        )
    return candidate


def _staging_value(value: str | date | None) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    return value


def create_candidate(
    person_id: int,
    category: str,
    key: str,
    value: str,
    *,
    source_id: int | None = None,
    valid_from: str | date | None = None,
    valid_to: str | date | None = None,
    visibility: str = "public",
    confidence: Any = 1.0,
    allow_overlap: bool = False,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Store extracted input without promoting it to the core facts table."""

    _validate_id(person_id, "person_id")
    if source_id is not None:
        _validate_id(source_id, "source_id")
    for field_name, field_value in (
        ("category", category),
        ("key", key),
        ("value", value),
        ("visibility", visibility),
    ):
        if not isinstance(field_value, str):
            raise CandidateInputError(f"{field_name} metin olmalıdır.")
    if not isinstance(allow_overlap, bool):
        raise CandidateInputError("allow_overlap boolean olmalıdır.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        cursor = active_connection.execute(
            """
            INSERT INTO fact_candidates (
                person_id, source_id, category, key, value,
                valid_from, valid_to, visibility, confidence, allow_overlap
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                source_id,
                category,
                key,
                value,
                _staging_value(valid_from),
                _staging_value(valid_to),
                visibility,
                confidence,
                int(allow_overlap),
            ),
        )
        if owns_connection:
            active_connection.commit()
        return get_candidate(cursor.lastrowid, connection=active_connection)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def get_candidate(
    candidate_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return a candidate by id."""

    _validate_id(candidate_id, "candidate_id")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        return _candidate_to_dict(_get_candidate_row(active_connection, candidate_id))
    finally:
        if owns_connection:
            active_connection.close()


def list_candidates(
    *,
    review_status: str | None = None,
    validation_status: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List candidates with optional workflow filters."""

    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise CandidateInputError("Geçersiz review_status.")
    if (
        validation_status is not None
        and validation_status not in VALIDATION_STATUSES
    ):
        raise CandidateInputError("Geçersiz validation_status.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        clauses = []
        parameters = []
        if review_status is not None:
            clauses.append("review_status = ?")
            parameters.append(review_status)
        if validation_status is not None:
            clauses.append("validation_status = ?")
            parameters.append(validation_status)

        query = "SELECT * FROM fact_candidates"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        rows = active_connection.execute(query, parameters).fetchall()
        return [_candidate_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()


def _ensure_pending(candidate: sqlite3.Row) -> None:
    if candidate["review_status"] != "pending":
        raise CandidateStateError(
            "Yalnızca pending bir candidate incelenebilir."
        )


def _collect_validation_issues(
    connection: sqlite3.Connection,
    candidate: sqlite3.Row,
) -> list[dict[str, str]]:
    """Dry-run promotion using the real core service rules."""

    issues: list[dict[str, str]] = []
    savepoint_name = "validate_candidate"
    connection.execute(f"SAVEPOINT {savepoint_name}")
    try:
        fact_id = add_fact(
            candidate["person_id"],
            candidate["category"],
            candidate["key"],
            candidate["value"],
            valid_from=candidate["valid_from"],
            valid_to=candidate["valid_to"],
            visibility=candidate["visibility"],
            confidence=candidate["confidence"],
            allow_overlap=bool(candidate["allow_overlap"]),
            connection=connection,
        )
        if candidate["source_id"] is not None:
            link_fact_source(
                fact_id,
                candidate["source_id"],
                connection=connection,
            )
    except (FactError, FactSourceError) as error:
        issues.append(
            {
                "code": type(error).__name__,
                "message": str(error),
            }
        )
    finally:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
    return issues


def _store_validation_report(
    connection: sqlite3.Connection,
    candidate_id: int,
    issues: list[dict[str, str]],
) -> None:
    validation_status = "invalid" if issues else "valid"
    connection.execute(
        """
        UPDATE fact_candidates
        SET validation_status = ?,
            validation_report = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            validation_status,
            json.dumps(issues, ensure_ascii=False),
            candidate_id,
        ),
    )


def validate_candidate(
    candidate_id: int,
    *,
    core_database_path: str | Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Validate a pending candidate without changing core data."""

    _validate_id(candidate_id, "candidate_id")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        attach_core_database(active_connection, core_database_path)
        candidate = _get_candidate_row(active_connection, candidate_id)
        _ensure_pending(candidate)
        issues = _collect_validation_issues(active_connection, candidate)
        _store_validation_report(active_connection, candidate_id, issues)
        if owns_connection:
            active_connection.commit()
        return get_candidate(candidate_id, connection=active_connection)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def approve_candidate(
    candidate_id: int,
    *,
    review_note: str | None = None,
    core_database_path: str | Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Validate and promote a candidate to core in one SQLite transaction."""

    _validate_id(candidate_id, "candidate_id")
    if review_note is not None and not isinstance(review_note, str):
        raise CandidateInputError("review_note metin olmalıdır.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        attach_core_database(active_connection, core_database_path)
        candidate = _get_candidate_row(active_connection, candidate_id)
        _ensure_pending(candidate)
        issues = _collect_validation_issues(active_connection, candidate)
        _store_validation_report(active_connection, candidate_id, issues)
        if issues:
            if owns_connection:
                active_connection.commit()
            raise CandidateValidationFailedError(issues)

        savepoint_name = "approve_candidate"
        active_connection.execute(f"SAVEPOINT {savepoint_name}")
        try:
            fact_id = add_fact(
                candidate["person_id"],
                candidate["category"],
                candidate["key"],
                candidate["value"],
                valid_from=candidate["valid_from"],
                valid_to=candidate["valid_to"],
                visibility=candidate["visibility"],
                confidence=candidate["confidence"],
                allow_overlap=bool(candidate["allow_overlap"]),
                connection=active_connection,
            )
            if candidate["source_id"] is not None:
                link_fact_source(
                    fact_id,
                    candidate["source_id"],
                    connection=active_connection,
                )
            active_connection.execute(
                """
                UPDATE fact_candidates
                SET review_status = 'approved',
                    validation_status = 'valid',
                    approved_fact_id = ?,
                    review_note = ?,
                    reviewed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (fact_id, review_note, candidate_id),
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

        return {
            "candidate": get_candidate(
                candidate_id,
                connection=active_connection,
            ),
            "fact": get_fact(fact_id, connection=active_connection),
        }
    except CandidateValidationFailedError:
        raise
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def reject_candidate(
    candidate_id: int,
    review_note: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Reject a candidate while retaining it for audit."""

    _validate_id(candidate_id, "candidate_id")
    if not isinstance(review_note, str) or not review_note.strip():
        raise CandidateInputError("Reject işlemi için review_note zorunludur.")

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        candidate = _get_candidate_row(active_connection, candidate_id)
        _ensure_pending(candidate)
        active_connection.execute(
            """
            UPDATE fact_candidates
            SET review_status = 'rejected',
                review_note = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (review_note.strip(), candidate_id),
        )
        if owns_connection:
            active_connection.commit()
        return get_candidate(candidate_id, connection=active_connection)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()
