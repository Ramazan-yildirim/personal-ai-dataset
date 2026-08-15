from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.migrations import (
    MigrationError,
    initialize_core_database,
)


def main():
    try:
        database_path, applied = initialize_core_database()
    except MigrationError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if applied:
        versions = ", ".join(f"{item.version:03d}" for item in applied)
        print(f"Uygulanan migration: {versions}")
    else:
        print("Veritabanı şeması zaten güncel.")
    print(f"Konum: {database_path}")


if __name__ == "__main__":
    main()
