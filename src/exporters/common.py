"""Shared deterministic and privacy-aware exporter utilities."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from src.database.connection import PROJECT_ROOT, get_connection


EXPORT_ROOT = PROJECT_ROOT / "data" / "exports"
ALLOWED_VISIBILITIES = {"public", "private", "internal"}


class ExportError(Exception):
    """Base exception for dataset export operations."""


class ExportValidationError(ExportError, ValueError):
    """Raised when exporter configuration is invalid."""


def normalize_visibilities(
    visibilities: Iterable[str] | None,
) -> tuple[str, ...]:
    values = tuple(visibilities) if visibilities is not None else ("public",)
    if not values:
        raise ExportValidationError("En az bir visibility seçilmelidir.")
    invalid = set(values) - ALLOWED_VISIBILITIES
    if invalid:
        raise ExportValidationError(
            f"Geçersiz visibility: {', '.join(sorted(invalid))}."
        )
    return tuple(sorted(set(values)))


def load_export_facts(
    *,
    visibilities: Iterable[str] | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Load active facts deterministically with person and source metadata."""

    normalized_visibilities = normalize_visibilities(visibilities)
    owns_connection = connection is None
    active_connection = connection or get_connection()
    active_connection.row_factory = sqlite3.Row
    placeholders = ", ".join("?" for _ in normalized_visibilities)
    try:
        rows = active_connection.execute(
            f"""
            SELECT
                facts.*,
                persons.name AS person_name
            FROM facts
            JOIN persons ON persons.id = facts.person_id
            WHERE facts.status = 'active'
              AND facts.visibility IN ({placeholders})
            ORDER BY
                persons.name,
                facts.category,
                facts.key,
                COALESCE(facts.valid_from, ''),
                COALESCE(facts.valid_to, ''),
                facts.id
            """,
            normalized_visibilities,
        ).fetchall()

        results = []
        for row in rows:
            fact = {key: row[key] for key in row.keys()}
            source_rows = active_connection.execute(
                """
                SELECT sources.id, sources.source_type, sources.title
                FROM sources
                JOIN fact_sources ON fact_sources.source_id = sources.id
                WHERE fact_sources.fact_id = ?
                ORDER BY sources.id
                """,
                (fact["id"],),
            ).fetchall()
            fact["sources"] = [
                {key: source[key] for key in source.keys()}
                for source in source_rows
            ]
            results.append(fact)
        return results
    finally:
        if owns_connection:
            active_connection.close()


def fact_text(fact: dict[str, Any]) -> str:
    """Render one atomic fact without adding unsupported claims."""

    text = (
        f"{fact['person_name']} — {fact['category']}.{fact['key']}: "
        f"{fact['value']}."
    )
    if fact["valid_from"] and fact["valid_to"]:
        text += (
            f" Geçerlilik: {fact['valid_from']} ile "
            f"{fact['valid_to']} arası."
        )
    elif fact["valid_from"]:
        text += f" Geçerlilik başlangıcı: {fact['valid_from']}."
    elif fact["valid_to"]:
        text += f" Geçerlilik bitişi: {fact['valid_to']}."
    return text


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> int:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in records
    ]
    content = "\n".join(lines)
    if content:
        content += "\n"
    write_text_atomic(path, content)
    return len(lines)
