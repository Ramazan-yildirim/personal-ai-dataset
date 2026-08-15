"""Safe ingestion of original documents into versioned raw storage."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from src.database.connection import PROJECT_ROOT
from src.database.sources import (
    SourceError,
    add_source,
    compute_file_hash,
    list_sources,
)


RAW_ROOT = PROJECT_ROOT / "data" / "raw"

SOURCE_DIRECTORIES = {
    "cv": "cv",
    "transcript": "transcript",
    "certificate": "certificates",
    "certificates": "certificates",
    "github": "github",
    "portfolio": "portfolio",
    "other": "other",
}

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
}


class IngestionError(Exception):
    """Base exception for raw document ingestion."""


class IngestionValidationError(IngestionError, ValueError):
    """Raised when an input document or destination is invalid."""


def _source_directory(source_type: str) -> str:
    if not isinstance(source_type, str) or not source_type.strip():
        raise IngestionValidationError("source_type boş olmayan bir metin olmalıdır.")
    normalized = source_type.strip().lower()
    try:
        return SOURCE_DIRECTORIES[normalized]
    except KeyError as error:
        allowed = ", ".join(sorted(SOURCE_DIRECTORIES))
        raise IngestionValidationError(
            f"source_type şu değerlerden biri olmalıdır: {allowed}."
        ) from error


def _input_document(input_path: str | Path) -> Path:
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise IngestionValidationError(f"Belge bulunamadı: {path}")
    if not path.is_file():
        raise IngestionValidationError(f"Belge yolu bir dosya olmalıdır: {path}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise IngestionValidationError(
            f"Desteklenmeyen belge uzantısı. İzin verilenler: {allowed}."
        )
    return path


def _available_destination(
    input_path: Path,
    target_directory: Path,
    file_hash: str,
) -> Path:
    destination = target_directory / input_path.name
    if not destination.exists():
        return destination
    if destination.resolve() == input_path:
        return destination
    if destination.is_file() and compute_file_hash(destination) == file_hash:
        return destination
    return target_directory / (
        f"{input_path.stem}_{file_hash[:8]}{input_path.suffix.lower()}"
    )


def ingest_document(
    source_type: str,
    title: str,
    input_path: str | Path,
    *,
    source_date: str | date | None = None,
    raw_root: str | Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Copy an immutable source into raw storage and register its provenance."""

    source_directory = _source_directory(source_type)
    input_document = _input_document(input_path)
    file_hash = compute_file_hash(input_document)

    for existing_source in list_sources(connection=connection):
        if existing_source["file_hash"] == file_hash:
            return {
                "source": existing_source,
                "raw_path": existing_source["file_path"],
                "copied": False,
                "duplicate": True,
            }

    target_root = Path(raw_root).resolve() if raw_root is not None else RAW_ROOT
    target_directory = target_root / source_directory
    target_directory.mkdir(parents=True, exist_ok=True)
    destination = _available_destination(
        input_document,
        target_directory,
        file_hash,
    )

    should_copy = destination.resolve() != input_document
    created_destination = False
    if should_copy and not destination.exists():
        shutil.copy2(input_document, destination)
        created_destination = True

    try:
        source = add_source(
            source_type,
            title,
            file_path=destination,
            source_date=source_date,
            file_hash=file_hash,
            connection=connection,
        )
    except SourceError:
        if created_destination:
            destination.unlink()
        raise

    return {
        "source": source,
        "raw_path": source["file_path"],
        "copied": created_destination,
        "duplicate": False,
    }
