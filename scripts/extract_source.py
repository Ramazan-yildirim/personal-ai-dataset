import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.sources import SourceError
from src.extraction.documents import ExtractionError, extract_source


def parse_args():
    parser = argparse.ArgumentParser(
        description="Kayıtlı source belgesinden staging metni çıkarır."
    )
    parser.add_argument("source_id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        result = extract_source(args.source_id)
    except (ExtractionError, SourceError) as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
