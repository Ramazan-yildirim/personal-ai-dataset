from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.append(str(PROJECT_ROOT))


from src.database.persons import (
    DuplicatePersonError,
    PersonError,
    create_person,
)


def main():
    person_name = input("Kişi adı: ").strip()
    try:
        person = create_person(person_name)
    except DuplicatePersonError as error:
        print("Bu kişi zaten veritabanında kayıtlı.")
        print(f"ID: {error.person['id']}")
        print(f"Ad: {error.person['name']}")
        return
    except PersonError as error:
        print(f"Hata: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print("Kişi başarıyla oluşturuldu.")
    print(f"ID: {person['id']}")
    print(f"Ad: {person['name']}")


if __name__ == "__main__":
    main()
