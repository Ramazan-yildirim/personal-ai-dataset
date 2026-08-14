"""Reusable operations for source provenance and file hashing."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from src.database.connection import PROJECT_ROOT, get_connection


class SourceError(Exception):
    """Base exception for source operations."""


class SourceValidationError(SourceError, ValueError):
    """Raised when source input or a source file is invalid."""


class SourceNotFoundError(SourceError):
    """Raised when a requested source does not exist."""


class DuplicateSourceError(SourceError):
    """Raised when the same source content or metadata already exists."""

    def __init__(self, source: dict[str, Any]):
        self.source = source
        super().__init__(
            f"Aynı kaynak zaten kayıtlı (source_id={source['id']})."
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


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceValidationError(f"{field_name} boş olmayan bir metin olmalıdır.")
    return value.strip()


def _optional_date(value: str | date | None, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise SourceValidationError(f"{field_name}, YYYY-MM-DD biçiminde olmalıdır.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise SourceValidationError(
            f"{field_name}, YYYY-MM-DD biçiminde geçerli bir tarih olmalıdır."
        ) from error


def _validate_source_id(source_id: int) -> None:
    if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
        raise SourceValidationError("source_id pozitif bir tam sayı olmalıdır.")


def _resolve_file_path(file_path: str | Path) -> Path:
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _stored_file_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def compute_file_hash(
    file_path: str | Path,
    *,
    algorithm: str = "sha256",
    chunk_size: int = 1024 * 1024,
) -> str:
    """Return a streaming content hash for a local source file."""

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise SourceValidationError("chunk_size pozitif bir tam sayı olmalıdır.")
    try:
        digest = hashlib.new(algorithm)
    except ValueError as error:
        raise SourceValidationError(
            f"Desteklenmeyen hash algoritması: {algorithm}."
        ) from error

    path = _resolve_file_path(file_path)
    if not path.exists():
        raise SourceValidationError(f"Kaynak dosya bulunamadı: {path}")
    if not path.is_file():
        raise SourceValidationError(f"Kaynak yolu bir dosya olmalıdır: {path}")

    with path.open("rb") as source_file:
        while chunk := source_file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _get_source_row(
    connection: sqlite3.Connection,
    source_id: int,
) -> sqlite3.Row:
    source = connection.execute(
        "SELECT * FROM sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    if source is None:
        raise SourceNotFoundError(
            f"source_id={source_id} için kaynak bulunamadı."
        )
    return source


def add_source(
    source_type: str,
    title: str,
    *,
    file_path: str | Path | None = None,
    source_date: str | date | None = None,
    file_hash: str | None = None,
    is_active: bool = True,
    hash_file: bool = True,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Validate and add a source, rejecting duplicate content."""

    normalized_type = _required_text(source_type, "source_type").lower()
    normalized_title = _required_text(title, "title")
    normalized_date = _optional_date(source_date, "source_date")
    if not isinstance(is_active, bool):
        raise SourceValidationError("is_active boolean olmalıdır.")
    if not isinstance(hash_file, bool):
        raise SourceValidationError("hash_file boolean olmalıdır.")

    normalized_path = None
    computed_hash = None
    if file_path is not None:
        resolved_path = _resolve_file_path(file_path)
        normalized_path = _stored_file_path(resolved_path)
        if hash_file:
            computed_hash = compute_file_hash(resolved_path)

    normalized_hash = None
    if file_hash is not None:
        normalized_hash = _required_text(file_hash, "file_hash").lower()
    if computed_hash is not None:
        if normalized_hash is not None and normalized_hash != computed_hash:
            raise SourceValidationError(
                "Verilen file_hash, dosyanın hesaplanan hash'iyle eşleşmiyor."
            )
        normalized_hash = computed_hash

    active_connection, owns_connection = _connection_or_default(connection)
    try:
        if normalized_hash is not None:
            duplicate = active_connection.execute(
                "SELECT * FROM sources WHERE file_hash = ? LIMIT 1",
                (normalized_hash,),
            ).fetchone()
        else:
            duplicate = active_connection.execute(
                """
                SELECT *
                FROM sources
                WHERE source_type = ?
                  AND title = ?
                  AND file_path IS ?
                  AND source_date IS ?
                LIMIT 1
                """,
                (
                    normalized_type,
                    normalized_title,
                    normalized_path,
                    normalized_date,
                ),
            ).fetchone()
        if duplicate is not None:
            raise DuplicateSourceError(_row_to_dict(duplicate))

        cursor = active_connection.execute(
            """
            INSERT INTO sources (
                source_type, title, file_path, source_date, file_hash, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_type,
                normalized_title,
                normalized_path,
                normalized_date,
                normalized_hash,
                int(is_active),
            ),
        )
        if owns_connection:
            active_connection.commit()
        return get_source(cursor.lastrowid, connection=active_connection)
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()


def get_source(
    source_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return a source by id."""

    _validate_source_id(source_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        return _row_to_dict(_get_source_row(active_connection, source_id))
    finally:
        if owns_connection:
            active_connection.close()


def list_sources(
    *,
    active_only: bool = False,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return sources in insertion order."""

    if not isinstance(active_only, bool):
        raise SourceValidationError("active_only boolean olmalıdır.")
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        query = "SELECT * FROM sources"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        rows = active_connection.execute(query).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        if owns_connection:
            active_connection.close()


def deactivate_source(
    source_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Deactivate a source without deleting its provenance record."""

    _validate_source_id(source_id)
    active_connection, owns_connection = _connection_or_default(connection)
    try:
        source = _get_source_row(active_connection, source_id)
        if source["is_active"]:
            active_connection.execute(
                "UPDATE sources SET is_active = 0 WHERE id = ?",
                (source_id,),
            )
            if owns_connection:
                active_connection.commit()
        return _row_to_dict(_get_source_row(active_connection, source_id))
    except Exception:
        if owns_connection:
            active_connection.rollback()
        raise
    finally:
        if owns_connection:
            active_connection.close()
