from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.staging_connection import initialize_staging_database


def main():
    database_path = initialize_staging_database()
    print("Staging veritabanı başarıyla oluşturuldu.")
    print(f"Konum: {database_path}")


if __name__ == "__main__":
    main()
