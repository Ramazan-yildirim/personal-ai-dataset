import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.facts import (
    FactError,
    close_fact,
    deprecate_fact,
    soft_delete_fact,
    supersede_fact,
)
from src.database.fact_sources import FactSourceError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fact yaşam döngüsü işlemlerini uygular."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    close_parser = commands.add_parser("close", help="Fact dönemini kapatır.")
    close_parser.add_argument("fact_id", type=int)
    close_parser.add_argument("valid_to")

    deprecate_parser = commands.add_parser(
        "deprecate",
        help="Fact'i güvenilmez olarak işaretler.",
    )
    deprecate_parser.add_argument("fact_id", type=int)

    delete_parser = commands.add_parser(
        "delete",
        help="Fact'i mantıksal olarak siler.",
    )
    delete_parser.add_argument("fact_id", type=int)

    supersede_parser = commands.add_parser(
        "supersede",
        help="Açık fact'i kapatıp yeni değerini ekler.",
    )
    supersede_parser.add_argument("fact_id", type=int)
    supersede_parser.add_argument("new_value")
    supersede_parser.add_argument("--valid-from", required=True)
    supersede_parser.add_argument("--previous-valid-to")
    supersede_parser.add_argument(
        "--visibility",
        choices=("public", "private", "internal"),
    )
    supersede_parser.add_argument("--confidence", type=float)
    supersede_parser.add_argument("--source-id", type=int)
    supersede_parser.add_argument("--allow-overlap", action="store_true")

    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "close":
            fact = close_fact(args.fact_id, args.valid_to)
        elif args.command == "deprecate":
            fact = deprecate_fact(args.fact_id)
        elif args.command == "delete":
            fact = soft_delete_fact(args.fact_id)
        else:
            fact = supersede_fact(
                args.fact_id,
                args.new_value,
                valid_from=args.valid_from,
                previous_valid_to=args.previous_valid_to,
                visibility=args.visibility,
                confidence=args.confidence,
                source_id=args.source_id,
                allow_overlap=args.allow_overlap,
            )
    except (FactError, FactSourceError) as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(fact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
