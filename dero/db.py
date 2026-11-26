"""The SQLite connection (one per request), the schema and the key/value settings."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def now_iso() -> str:
    """The current time in UTC as an ISO string (how every date is stored)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> sqlite3.Connection:
    """The connection of the current request, opened on first use."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn

    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    """Close the request's connection (Flask calls this when the request ends)."""
    conn = g.pop("db", None)

    if conn is not None:
        conn.close()


def init_db() -> None:
    """Create the tables if they do not exist yet."""
    schema = (Path(__file__).parent / "schema.sql").read_text()
    get_db().executescript(schema)


def get_setting(key: str, default: str = "") -> str:
    """A saved setting, or the default."""
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Save a setting, replacing an earlier value."""
    db = get_db()
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()
