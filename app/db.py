"""Minimal SQLite storage for pending meal confirmations."""
import sqlite3
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.config import settings


def _db_path() -> str:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return url


@contextmanager
def _conn():
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS pending_meals (
                id          TEXT PRIMARY KEY,
                chat_id     INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                analysis    TEXT NOT NULL,
                created_at  INTEGER NOT NULL
            );
            """
        )


def save_pending_meal(meal_id: str, chat_id: int, user_id: int,
                      username: Optional[str], analysis: dict) -> None:
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO pending_meals
               (id, chat_id, user_id, username, analysis, created_at)
               VALUES(?,?,?,?,?,?)""",
            (meal_id, chat_id, user_id, username or "",
             json.dumps(analysis), int(time.time())),
        )


def consume_pending_meal(meal_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM pending_meals WHERE id=?", (meal_id,)
        ).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM pending_meals WHERE id=?", (meal_id,))
        return {
            "chat_id": row["chat_id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "analysis": json.loads(row["analysis"]),
            "created_at": row["created_at"],
        }
