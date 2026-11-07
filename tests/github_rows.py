"""Insert minimal GitHub rows for tests."""


def add_item(conn, id, number, kind, login, created, vanished=None):
    conn.execute(
        "INSERT INTO items (id, number, kind, author_login, title, body, state,"
        " created_at, updated_at, vanished_at)"
        " VALUES (?, ?, ?, ?, '', '', 'open', ?, ?, ?)",
        (id, number, kind, login, created, created, vanished),
    )


def add_event(conn, id, item_id, kind, login, created, vanished=None):
    conn.execute(
        "INSERT INTO events (id, item_id, kind, author_login, created_at, vanished_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (id, item_id, kind, login, created, vanished),
    )


def add_commit(conn, sha, ts, name, email, raw_name=None, raw_email=None):
    conn.execute(
        "INSERT INTO commits VALUES (?, ?, ?, ?, ?, ?, ?, '', '')",
        (sha, ts, ts, name, email, raw_name or name, raw_email or email),
    )


def add_commit_login(conn, sha, email, login):
    conn.execute(
        "INSERT INTO commit_logins (sha, email, name, login) VALUES (?, ?, '', ?)",
        (sha, email, login),
    )
