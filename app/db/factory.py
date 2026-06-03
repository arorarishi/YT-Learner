import os

from .base_database import BaseDatabase
from .sqlite_database import SQLiteDatabase


def get_db() -> BaseDatabase:
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        db_path = os.path.join(os.path.dirname(__file__), "..", "transcripts.db")
        return SQLiteDatabase(os.path.normpath(db_path))
    if db_type == "postgres":
        from .postgres_database import PostgresDatabase
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL must be set when DB_TYPE=postgres")
        return PostgresDatabase(url)
    raise NotImplementedError(f"Unsupported DB_TYPE: {db_type}")
