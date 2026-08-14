from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.append(str(PROJECT_ROOT))


from src.database.connection import get_connection


def list_persons():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM persons
            ORDER BY id
            """
        )

        persons = cursor.fetchall()

        if not persons:
            print("Veritabanında kayıtlı kişi bulunamadı.")
            return

        print("\nKayıtlı kişiler\n")

        for person in persons:
            print(
                f"ID: {person['id']} | "
                f"Ad: {person['name']} | "
                f"Oluşturulma: {person['created_at']}"
            )

    finally:
        connection.close()


if __name__ == "__main__":
    list_persons()