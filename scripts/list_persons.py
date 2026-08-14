from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.append(str(PROJECT_ROOT))


from src.database.persons import list_persons


def main():
    persons = list_persons()
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


if __name__ == "__main__":
    main()
