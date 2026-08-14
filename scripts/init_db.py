import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = PROJECT_ROOT / "data" / "core" / "personal_data.db"
SCHEMA_PATH = PROJECT_ROOT / "src" / "database" / "schema.sql"


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
        schema = file.read()

    connection = sqlite3.connect(DATABASE_PATH)

    try:
        connection.executescript(schema)
        connection.commit()

        print("Veritabanı başarıyla oluşturuldu.")
        print(f"Konum: {DATABASE_PATH}")

    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()