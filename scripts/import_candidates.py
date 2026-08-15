import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.extraction.candidate_import import (
    CandidateImportError,
    import_candidate_bundle,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Structured extraction bundle'ını staging'e import eder."
    )
    parser.add_argument("bundle_path")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        result = import_candidate_bundle(args.bundle_path)
    except CandidateImportError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
