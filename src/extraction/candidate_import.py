"""Import structured extraction results into the staging candidate database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.database.staging_connection import get_staging_connection
from src.validation.candidates import CandidateError, create_candidate


class CandidateImportError(Exception):
    """Raised when a structured extraction bundle is invalid."""


def _required_positive_id(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateImportError(
            f"{field_name} pozitif bir tam sayı olmalıdır."
        )
    return value


def _load_bundle(bundle_path: str | Path) -> dict[str, Any]:
    path = Path(bundle_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise CandidateImportError(f"Candidate bundle bulunamadı: {path}")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateImportError(f"Geçersiz candidate bundle JSON: {path}") from error
    if not isinstance(bundle, dict):
        raise CandidateImportError("Candidate bundle bir JSON object olmalıdır.")
    return bundle


def _existing_candidate_id(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    source_id: int,
    candidate: dict[str, Any],
) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM fact_candidates
        WHERE person_id = ?
          AND source_id = ?
          AND category = ?
          AND key = ?
          AND value = ?
          AND valid_from IS ?
          AND valid_to IS ?
          AND visibility = ?
          AND confidence IS ?
          AND allow_overlap = ?
        LIMIT 1
        """,
        (
            person_id,
            source_id,
            candidate.get("category"),
            candidate.get("key"),
            candidate.get("value"),
            candidate.get("valid_from"),
            candidate.get("valid_to"),
            candidate.get("visibility", "public"),
            candidate.get("confidence", 1.0),
            int(bool(candidate.get("allow_overlap", False))),
        ),
    ).fetchone()
    return None if row is None else int(row["id"])


def import_candidate_bundle(
    bundle_path: str | Path,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Import all candidates atomically and skip exact previous imports."""

    bundle = _load_bundle(bundle_path)
    person_id = _required_positive_id(bundle.get("person_id"), "person_id")
    source_id = _required_positive_id(bundle.get("source_id"), "source_id")
    candidates = bundle.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CandidateImportError(
            "candidates boş olmayan bir JSON array olmalıdır."
        )

    owns_connection = connection is None
    active_connection = connection or get_staging_connection()
    active_connection.row_factory = sqlite3.Row
    created_ids: list[int] = []
    skipped_ids: list[int] = []
    savepoint_name = "import_candidate_bundle"
    active_connection.execute(f"SAVEPOINT {savepoint_name}")
    try:
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise CandidateImportError(
                    f"candidates[{index}] bir JSON object olmalıdır."
                )

            existing_id = _existing_candidate_id(
                active_connection,
                person_id=person_id,
                source_id=source_id,
                candidate=candidate,
            )
            if existing_id is not None:
                skipped_ids.append(existing_id)
                continue

            try:
                created = create_candidate(
                    person_id,
                    candidate.get("category"),
                    candidate.get("key"),
                    candidate.get("value"),
                    source_id=source_id,
                    valid_from=candidate.get("valid_from"),
                    valid_to=candidate.get("valid_to"),
                    visibility=candidate.get("visibility", "public"),
                    confidence=candidate.get("confidence", 1.0),
                    allow_overlap=candidate.get("allow_overlap", False),
                    connection=active_connection,
                )
            except CandidateError as error:
                raise CandidateImportError(
                    f"candidates[{index}] geçersiz: {error}"
                ) from error
            created_ids.append(created["id"])
    except Exception:
        active_connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        if owns_connection:
            active_connection.rollback()
        raise
    else:
        active_connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        if owns_connection:
            active_connection.commit()
    finally:
        if owns_connection:
            active_connection.close()

    return {
        "person_id": person_id,
        "source_id": source_id,
        "created_candidate_ids": created_ids,
        "skipped_candidate_ids": skipped_ids,
    }
