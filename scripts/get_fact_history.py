import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.facts import FactError, get_fact_history


def parse_args():
    parser = argparse.ArgumentParser(description="Bir fact key'inin geçmişini getirir.")
    parser.add_argument("person_id", type=int)
    parser.add_argument("category")
    parser.add_argument("key")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        facts = get_fact_history(args.person_id, args.category, args.key)
    except FactError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(facts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
