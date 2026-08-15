"""Document and chunk JSONL export for a separate RAG project."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from src.exporters.common import (
    EXPORT_ROOT,
    ExportValidationError,
    fact_text,
    load_export_facts,
    write_jsonl_atomic,
)


def chunk_text(
    text: str,
    *,
    max_chars: int = 800,
    overlap_chars: int = 100,
) -> list[str]:
    """Split text deterministically without dropping overlap context."""

    if max_chars <= 0:
        raise ExportValidationError("max_chars pozitif olmalıdır.")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ExportValidationError(
            "overlap_chars, 0 ile max_chars arasında olmalıdır."
        )
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return [chunk for chunk in chunks if chunk]


def _document_record(fact: dict[str, object]) -> dict[str, object]:
    return {
        "document_id": f"fact_{fact['id']}",
        "person_id": fact["person_id"],
        "category": fact["category"],
        "key": fact["key"],
        "visibility": fact["visibility"],
        "valid_from": fact["valid_from"],
        "valid_to": fact["valid_to"],
        "source_ids": [source["id"] for source in fact["sources"]],
        "text": fact_text(fact),
    }


def export_rag(
    *,
    output_dir: str | Path | None = None,
    visibilities: Iterable[str] | None = None,
    max_chars: int = 800,
    overlap_chars: int = 100,
    connection: sqlite3.Connection | None = None,
) -> dict[str, object]:
    """Write deterministic fact documents and chunks."""

    facts = load_export_facts(
        visibilities=visibilities,
        connection=connection,
    )
    documents = [_document_record(fact) for fact in facts]
    chunks = []
    for document in documents:
        for index, text in enumerate(
            chunk_text(
                document["text"],
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        ):
            chunks.append(
                {
                    "chunk_id": f"{document['document_id']}_chunk_{index}",
                    "document_id": document["document_id"],
                    "category": document["category"],
                    "key": document["key"],
                    "visibility": document["visibility"],
                    "source_ids": document["source_ids"],
                    "text": text,
                }
            )

    target = (
        Path(output_dir).resolve()
        if output_dir is not None
        else EXPORT_ROOT / "rag"
    )
    documents_path = target / "documents.jsonl"
    chunks_path = target / "chunks.jsonl"
    document_count = write_jsonl_atomic(documents_path, documents)
    chunk_count = write_jsonl_atomic(chunks_path, chunks)
    return {
        "fact_count": len(facts),
        "document_count": document_count,
        "chunk_count": chunk_count,
        "documents": str(documents_path),
        "chunks": str(chunks_path),
    }
