from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.append(str(PROJECT_ROOT))


from src.database.connection import get_connection


def create_person(name):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, name
            FROM persons
            WHERE name = ?
            """,
            (name,)
        )

        existing_person = cursor.fetchone()

        if existing_person:
            print("Bu kişi zaten veritabanında kayıtlı.")
            print(f"ID: {existing_person['id']}")
            print(f"Ad: {existing_person['name']}")
            return existing_person["id"]

        cursor.execute(
            """
            INSERT INTO persons (name)
            VALUES (?)
            """,
            (name,)
        )

        connection.commit()

        person_id = cursor.lastrowid

        print("Kişi başarıyla oluşturuldu.")
        print(f"ID: {person_id}")
        print(f"Ad: {name}")

        return person_id

    finally:
        connection.close()


if __name__ == "__main__":
    person_name = input("Kişi adı: ").strip()

    if not person_name:
        raise SystemExit("Kişi adı boş olamaz.")

    create_person(person_name)
