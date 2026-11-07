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

-- GitHub PRs and issues. Logins of bot accounts end in "[bot]"; deleted
-- accounts ("ghost") have a NULL login. vanished_at is set when a full fetch
-- no longer finds the item; the row is kept but left out of live_items.
CREATE TABLE IF NOT EXISTS items (
    id               TEXT PRIMARY KEY,
    number           INTEGER NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('pr', 'issue')),
    author_login     TEXT,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    state            TEXT NOT NULL,
    state_reason     TEXT,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    closed_at        INTEGER,
    merged_at        INTEGER,
    merged_by_login  TEXT,
    merge_commit_sha TEXT,
    vanished_at      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_items_kind ON items (kind, number);

-- Current labels; replaced whenever the item is re-fetched.
CREATE TABLE IF NOT EXISTS item_labels (
    item_id TEXT NOT NULL REFERENCES items(id),
    label   TEXT NOT NULL,
    PRIMARY KEY (item_id, label)
);

-- Reviews and comments: who and when, no bodies. vanished_at is set when a
-- re-fetch of the item no longer includes the event.
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    item_id      TEXT NOT NULL REFERENCES items(id),
    kind         TEXT NOT NULL CHECK (kind IN ('review', 'comment')),
    author_login TEXT,
    created_at   INTEGER NOT NULL,
    review_state TEXT,
    vanished_at  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_events_item ON events (item_id);

-- GitHub's view of each main-branch commit's authors and co-authors. email is
-- raw (GitHub doesn't apply .mailmap); login is NULL when not linked.
CREATE TABLE IF NOT EXISTS commit_logins (
    sha   TEXT NOT NULL,
    email TEXT NOT NULL,
    name  TEXT NOT NULL,
    login TEXT,
    PRIMARY KEY (sha, email)
);

-- One release per major.minor version: its earliest final tag (see releases.py).
CREATE TABLE IF NOT EXISTS releases (
    version     TEXT PRIMARY KEY,
    tag         TEXT NOT NULL,
    released_at INTEGER NOT NULL
);

-- Model replies keyed by a hash of (model, task, prompt, schema); see llm.py.
CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- Analyses read these, so vanished rows are excluded in one place.
CREATE VIEW IF NOT EXISTS live_items AS
    SELECT * FROM items WHERE vanished_at IS NULL;
CREATE VIEW IF NOT EXISTS live_events AS
    SELECT e.* FROM events e JOIN items i ON i.id = e.item_id
    WHERE e.vanished_at IS NULL AND i.vanished_at IS NULL;
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
