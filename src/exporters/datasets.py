"""One-call export orchestration for the local dataset control center."""

from __future__ import annotations

from src.exporters.finetuning import export_finetuning
from src.exporters.rag import export_rag
from src.exporters.transformer import export_transformer


def export_all_datasets() -> dict[str, dict[str, object]]:
    """Regenerate every public-default dataset in `data/exports/`."""

    return {
        "transformer": export_transformer(),
        "finetuning": export_finetuning(),
        "rag": export_rag(),
    }
