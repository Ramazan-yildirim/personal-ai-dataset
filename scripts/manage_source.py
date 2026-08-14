import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.sources import SourceError, deactivate_source


def parse_args():
    parser = argparse.ArgumentParser(description="Source yaşam döngüsünü yönetir.")
    commands = parser.add_subparsers(dest="command", required=True)
    deactivate_parser = commands.add_parser(
        "deactivate",
        help="Kaynağı fiziksel olarak silmeden devre dışı bırakır.",
    )
    deactivate_parser.add_argument("source_id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        source = deactivate_source(args.source_id)
    except SourceError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(source, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
