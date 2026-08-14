import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.facts import FactError, add_fact


def parse_args():
    parser = argparse.ArgumentParser(description="Kişiye doğrulanmış bir fact ekler.")
    parser.add_argument("person_id", type=int)
    parser.add_argument("category")
    parser.add_argument("key")
    parser.add_argument("value")
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-to")
    parser.add_argument(
        "--visibility",
        choices=("public", "private", "internal"),
        default="public",
    )
    parser.add_argument(
        "--status",
        choices=("active", "deprecated", "deleted"),
        default="active",
    )
    parser.add_argument("--confidence", type=float, default=1.0)
    parser.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Bu key bilinçli olarak çok değerliyse dönem çakışmasına izin verir.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        fact_id = add_fact(
            args.person_id,
            args.category,
            args.key,
            args.value,
            valid_from=args.valid_from,
            valid_to=args.valid_to,
            visibility=args.visibility,
            status=args.status,
            confidence=args.confidence,
            allow_overlap=args.allow_overlap,
        )
    except FactError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"Fact başarıyla oluşturuldu. ID: {fact_id}")


if __name__ == "__main__":
    main()
