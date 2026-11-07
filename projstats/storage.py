"""SQLite cache for fetched history."""

import sqlite3
from pathlib import Path

SCHEMA = """
-- Non-merge commits reachable from HEAD. author_* has .mailmap applied;
-- raw_* is what the commit itself says, kept so a changed .mailmap can be
-- re-applied and so the latest email domain stays visible.
CREATE TABLE IF NOT EXISTS commits (
    sha          TEXT PRIMARY KEY,
    authored_at  INTEGER NOT NULL,
    committed_at INTEGER NOT NULL,
    author_name  TEXT NOT NULL,
    author_email TEXT NOT NULL,
    raw_name     TEXT NOT NULL,
    raw_email    TEXT NOT NULL,
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL
);

-- People credited by Co-authored-by trailers, with the same raw/mapped split.
CREATE TABLE IF NOT EXISTS commit_coauthors (
    sha       TEXT NOT NULL REFERENCES commits(sha) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    email     TEXT NOT NULL,
    raw_name  TEXT NOT NULL,
    raw_email TEXT NOT NULL,
    PRIMARY KEY (sha, raw_email)
);

CREATE TABLE IF NOT EXISTS fetch_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM fetch_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO fetch_state (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
