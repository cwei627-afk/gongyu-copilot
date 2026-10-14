"""Explicitly initialize small fixtures; existing database files are never reseeded."""
import sqlite3
from pathlib import Path

from app.db import data_directory


def initialize(data_dir: Path) -> list[str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    created = []
    sql_dir = Path(__file__).resolve().parent / "sql"
    for system in ("mes", "erp", "wms"):
        path = data_dir / f"{system}.db"
        if path.exists():
            continue
        connection = sqlite3.connect(path)
        try:
            connection.executescript((sql_dir / f"{system}.sql").read_text(encoding="utf-8"))
        finally:
            connection.close()
        created.append(path.name)
    return created


if __name__ == "__main__":
    directory = data_directory()
    print(f"Data directory: {directory}")
    print(f"Created: {initialize(directory)} (existing files skipped)")
