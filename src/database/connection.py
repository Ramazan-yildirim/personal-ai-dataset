import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATABASE_PATH = PROJECT_ROOT / "data" / "core" / "personal_data.db"


def get_connection(
    database_path: str | Path | None = None,
) -> sqlite3.Connection:
    path = Path(database_path) if database_path is not None else DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection
