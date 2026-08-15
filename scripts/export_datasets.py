import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.exporters.common import EXPORT_ROOT, ExportError
from src.exporters.finetuning import export_finetuning
from src.exporters.rag import export_rag
from src.exporters.transformer import export_transformer


def parse_args():
    parser = argparse.ArgumentParser(
        description="Core facts'ten yeniden üretilebilir model datasetleri oluşturur."
    )
    parser.add_argument(
        "target",
        choices=("transformer", "finetuning", "rag", "all"),
    )
    parser.add_argument("--output-dir")
    parser.add_argument("--include-private", action="store_true")
    parser.add_argument("--include-internal", action="store_true")
    parser.add_argument("--supplemental-dir")
    parser.add_argument("--seed", default="personal-ai-dataset-v1")
    parser.add_argument("--max-chars", type=int, default=800)
    parser.add_argument("--overlap-chars", type=int, default=100)
    return parser.parse_args()


def _visibilities(args):
    values = ["public"]
    if args.include_private:
        values.append("private")
    if args.include_internal:
        values.append("internal")
    return values


def main():
    args = parse_args()
    visibilities = _visibilities(args)
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else EXPORT_ROOT
    )

    try:
        results = {}
        if args.target in {"transformer", "all"}:
            target_dir = (
                output_root / "transformer"
                if args.target == "all"
                else output_root
            )
            results["transformer"] = export_transformer(
                output_dir=target_dir,
                supplemental_dir=args.supplemental_dir,
                visibilities=visibilities,
            )
        if args.target in {"finetuning", "all"}:
            target_dir = (
                output_root / "finetuning"
                if args.target == "all"
                else output_root
            )
            results["finetuning"] = export_finetuning(
                output_dir=target_dir,
                visibilities=visibilities,
                seed=args.seed,
            )
        if args.target in {"rag", "all"}:
            target_dir = output_root / "rag" if args.target == "all" else output_root
            results["rag"] = export_rag(
                output_dir=target_dir,
                visibilities=visibilities,
                max_chars=args.max_chars,
                overlap_chars=args.overlap_chars,
            )
    except ExportError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
