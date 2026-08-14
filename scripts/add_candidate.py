import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.validation.candidates import CandidateError, create_candidate


def parse_args():
    parser = argparse.ArgumentParser(
        description="Doğrulanmamış bir fact candidate oluşturur."
    )
    parser.add_argument("person_id", type=int)
    parser.add_argument("category")
    parser.add_argument("key")
    parser.add_argument("value")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-to")
    parser.add_argument("--visibility", default="public")
    parser.add_argument("--confidence", type=float, default=1.0)
    parser.add_argument("--allow-overlap", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        candidate = create_candidate(
            args.person_id,
            args.category,
            args.key,
            args.value,
            source_id=args.source_id,
            valid_from=args.valid_from,
            valid_to=args.valid_to,
            visibility=args.visibility,
            confidence=args.confidence,
            allow_overlap=args.allow_overlap,
        )
    except CandidateError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(candidate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
