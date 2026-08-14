import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.fact_sources import FactSourceError, link_fact_source


def parse_args():
    parser = argparse.ArgumentParser(description="Fact'i doğrulayan kaynağa bağlar.")
    parser.add_argument("fact_id", type=int)
    parser.add_argument("source_id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        link = link_fact_source(args.fact_id, args.source_id)
    except FactSourceError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(link, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
