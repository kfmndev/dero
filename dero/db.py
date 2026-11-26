"""The SQLite connection (one per request), the schema and the key/value settings."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn

    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)

    if conn is not None:
        conn.close()


def init_db():
    schema = (Path(__file__).parent / "schema.sql").read_text()
    get_db().executescript(schema)


def get_setting(key: str, default: str = "") -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    db = get_db()
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) " "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()
