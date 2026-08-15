"""Chat JSONL export for a separate fine-tuning project."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable

from src.exporters.common import (
    EXPORT_ROOT,
    fact_text,
    load_export_facts,
    write_jsonl_atomic,
)


def _split_name(fact_id: int, seed: str) -> str:
    digest = hashlib.sha256(f"{seed}:{fact_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


def _training_record(fact: dict[str, object]) -> dict[str, object]:
    question = (
        f"{fact['person_name']} için {fact['category']}.{fact['key']} "
        "bilgisi nedir?"
    )
    return {
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": fact_text(fact)},
        ]
    }


def export_finetuning(
    *,
    output_dir: str | Path | None = None,
    visibilities: Iterable[str] | None = None,
    seed: str = "personal-ai-dataset-v1",
    connection: sqlite3.Connection | None = None,
) -> dict[str, object]:
    """Write deterministic train/validation/test chat JSONL files."""

    facts = load_export_facts(
        visibilities=visibilities,
        connection=connection,
    )
    splits = {"train": [], "validation": [], "test": []}
    for fact in facts:
        splits[_split_name(fact["id"], seed)].append(_training_record(fact))
    if facts and not splits["train"]:
        fallback_split = next(
            name for name in ("validation", "test") if splits[name]
        )
        splits["train"].append(splits[fallback_split].pop(0))

    target = (
        Path(output_dir).resolve()
        if output_dir is not None
        else EXPORT_ROOT / "finetuning"
    )
    result: dict[str, object] = {"fact_count": len(facts), "files": {}}
    for split_name, records in splits.items():
        path = target / f"{split_name}.jsonl"
        count = write_jsonl_atomic(path, records)
        result["files"][split_name] = {
            "path": str(path),
            "record_count": count,
        }
    return result
