import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATABASE_PATH = PROJECT_ROOT / "data" / "core" / "personal_data.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection