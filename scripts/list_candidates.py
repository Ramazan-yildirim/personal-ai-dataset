import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.validation.candidates import CandidateError, list_candidates


def parse_args():
    parser = argparse.ArgumentParser(description="Fact candidate kayıtlarını listeler.")
    parser.add_argument(
        "--review-status",
        choices=("pending", "approved", "rejected"),
    )
    parser.add_argument(
        "--validation-status",
        choices=("pending", "valid", "invalid"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        candidates = list_candidates(
            review_status=args.review_status,
            validation_status=args.validation_status,
        )
    except CandidateError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
