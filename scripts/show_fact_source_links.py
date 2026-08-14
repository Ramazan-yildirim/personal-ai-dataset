import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.fact_sources import (
    FactSourceError,
    get_facts_for_source,
    get_sources_for_fact,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Fact-source bağlantılarını gösterir.")
    commands = parser.add_subparsers(dest="command", required=True)

    fact_parser = commands.add_parser("fact", help="Fact'in kaynaklarını gösterir.")
    fact_parser.add_argument("fact_id", type=int)
    fact_parser.add_argument("--active-only", action="store_true")

    source_parser = commands.add_parser(
        "source",
        help="Kaynağın doğruladığı fact'leri gösterir.",
    )
    source_parser.add_argument("source_id", type=int)
    source_parser.add_argument("--active-only", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "fact":
            records = get_sources_for_fact(
                args.fact_id,
                active_only=args.active_only,
            )
        else:
            records = get_facts_for_source(
                args.source_id,
                active_only=args.active_only,
            )
    except FactSourceError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
