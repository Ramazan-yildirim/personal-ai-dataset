import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.sources import SourceError, list_sources


def parse_args():
    parser = argparse.ArgumentParser(description="Kayıtlı kaynakları listeler.")
    parser.add_argument("--active-only", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        sources = list_sources(active_only=args.active_only)
    except SourceError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(sources, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
