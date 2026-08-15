"""Plain-text corpus export for a separate Transformer project."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from src.database.connection import PROJECT_ROOT
from src.exporters.common import (
    EXPORT_ROOT,
    fact_text,
    load_export_facts,
    write_text_atomic,
)


SUPPLEMENTAL_ROOT = PROJECT_ROOT / "data" / "supplemental" / "transformer"


def _supplemental_texts(root: Path) -> list[str]:
    if not root.exists():
        return []
    texts = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                texts.append(text)
    return texts


def export_transformer(
    *,
    output_dir: str | Path | None = None,
    supplemental_dir: str | Path | None = None,
    visibilities: Iterable[str] | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, object]:
    """Write personal and optional supplemental corpora."""

    facts = load_export_facts(
        visibilities=visibilities,
        connection=connection,
    )
    personal_parts = [fact_text(fact) for fact in facts]
    personal_corpus = "\n".join(personal_parts)
    if personal_corpus:
        personal_corpus += "\n"

    target = (
        Path(output_dir).resolve()
        if output_dir is not None
        else EXPORT_ROOT / "transformer"
    )
    personal_path = target / "personal_corpus.txt"
    full_path = target / "full_corpus.txt"
    write_text_atomic(personal_path, personal_corpus)

    supplemental_root = (
        Path(supplemental_dir).resolve()
        if supplemental_dir is not None
        else SUPPLEMENTAL_ROOT
    )
    supplemental_parts = _supplemental_texts(supplemental_root)
    full_parts = personal_parts + supplemental_parts
    full_corpus = "\n\n".join(full_parts)
    if full_corpus:
        full_corpus += "\n"
    write_text_atomic(full_path, full_corpus)

    return {
        "fact_count": len(facts),
        "supplemental_document_count": len(supplemental_parts),
        "personal_corpus": str(personal_path),
        "full_corpus": str(full_path),
    }
