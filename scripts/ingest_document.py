import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.sources import SourceError
from src.ingestion.documents import IngestionError, ingest_document


def parse_args():
    parser = argparse.ArgumentParser(
        description="Belgeyi güvenli raw storage'a kopyalayıp source kaydı oluşturur."
    )
    parser.add_argument(
        "source_type",
        choices=(
            "cv",
            "transcript",
            "certificate",
            "github",
            "portfolio",
            "other",
        ),
    )
    parser.add_argument("title")
    parser.add_argument("input_path")
    parser.add_argument("--source-date")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        result = ingest_document(
            args.source_type,
            args.title,
            args.input_path,
            source_date=args.source_date,
        )
    except (IngestionError, SourceError) as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
