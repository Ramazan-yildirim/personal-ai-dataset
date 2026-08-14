import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.validation.candidates import (
    CandidateError,
    CandidateValidationFailedError,
    approve_candidate,
    reject_candidate,
    validate_candidate,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Candidate validation ve review işlemlerini yürütür."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser(
        "validate",
        help="Core kurallarıyla dry-run validation yapar.",
    )
    validate_parser.add_argument("candidate_id", type=int)

    approve_parser = commands.add_parser(
        "approve",
        help="Valid candidate'ı core fact'e dönüştürür.",
    )
    approve_parser.add_argument("candidate_id", type=int)
    approve_parser.add_argument("--note")

    reject_parser = commands.add_parser(
        "reject",
        help="Candidate'ı audit kaydını koruyarak reddeder.",
    )
    reject_parser.add_argument("candidate_id", type=int)
    reject_parser.add_argument("--note", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "validate":
            result = validate_candidate(args.candidate_id)
        elif args.command == "approve":
            result = approve_candidate(
                args.candidate_id,
                review_note=args.note,
            )
        else:
            result = reject_candidate(args.candidate_id, args.note)
    except CandidateValidationFailedError as error:
        print(
            json.dumps(error.issues, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    except CandidateError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
