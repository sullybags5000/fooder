"""Minimal SQLite storage for Fitbit tokens and pending meal confirmations.

Schema kept simple & synchronous — one user = one Telegram chat_id.
"""
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
            CREATE TABLE IF NOT EXISTS fitbit_tokens (
                chat_id          INTEGER PRIMARY KEY,
                fitbit_user_id   TEXT,
                access_token     TEXT NOT NULL,
                refresh_token    TEXT NOT NULL,
                expires_at       INTEGER NOT NULL,
                updated_at       INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS oauth_states (
                state      TEXT PRIMARY KEY,
                chat_id    INTEGER NOT NULL,
                verifier   TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_meals (
                id          TEXT PRIMARY KEY,
                chat_id     INTEGER NOT NULL,
                analysis    TEXT NOT NULL,
                created_at  INTEGER NOT NULL
            );
            """
        )


# --- Fitbit tokens ---

def save_fitbit_tokens(chat_id: int, fitbit_user_id: str, access: str, refresh: str, expires_in: int) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO fitbit_tokens(chat_id, fitbit_user_id, access_token, refresh_token, expires_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET
                fitbit_user_id=excluded.fitbit_user_id,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (chat_id, fitbit_user_id, access, refresh, int(time.time()) + expires_in, int(time.time())),
        )


def get_fitbit_tokens(chat_id: int) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM fitbit_tokens WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None


def delete_fitbit_tokens(chat_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM fitbit_tokens WHERE chat_id=?", (chat_id,))


# --- OAuth PKCE state ---

def save_oauth_state(state: str, chat_id: int, verifier: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO oauth_states(state, chat_id, verifier, created_at) VALUES(?,?,?,?)",
            (state, chat_id, verifier, int(time.time())),
        )


def consume_oauth_state(state: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM oauth_states WHERE state=?", (state,)).fetchone()
        if row:
            con.execute("DELETE FROM oauth_states WHERE state=?", (state,))
        return dict(row) if row else None


# --- Pending meal confirmations ---

def save_pending_meal(meal_id: str, chat_id: int, analysis: dict) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO pending_meals(id, chat_id, analysis, created_at) VALUES(?,?,?,?)",
            (meal_id, chat_id, json.dumps(analysis), int(time.time())),
        )


def consume_pending_meal(meal_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM pending_meals WHERE id=?", (meal_id,)).fetchone()
        if row:
            con.execute("DELETE FROM pending_meals WHERE id=?", (meal_id,))
            return json.loads(row["analysis"])
        return None
