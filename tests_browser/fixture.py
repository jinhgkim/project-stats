"""A small two-project site, plus one unlisted project, built the way the daily
deploy builds it and served on localhost, for the browser tests."""

import contextlib
import functools
import http.server
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from projstats import config, deploy, storage
from tests.github_rows import add_commit, add_commit_login, add_event, add_item

# Listed out of alphabetical order, so the switcher order is the list order.
PROJECTS = ["zulu", "alpha"]
UNLISTED = "ghost"


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


def fill(conn, extra: bool) -> None:
    for sha, when, name, login in [
        ("a1", "2019-03-05T10:00", "Ann Lee", "ann"),
        ("a2", "2020-03-05T10:00", "Ann Lee", "ann"),
        ("a3", "2021-03-05T10:00", "Ann Lee", "ann"),
        ("b1", "2020-06-05T10:00", "Bo Ray", "bo"),
    ]:
        email = f"{login}@x.example"
        add_commit(conn, sha, ts(when), name, email)
        add_commit_login(conn, sha, email, login)
    add_item(conn, "P1", 1, "pr", "bo", ts("2020-05-01T00:00"))
    add_item(conn, "I2", 2, "issue", "cy", ts("2020-07-01T00:00"))
    add_event(conn, "R1", "P1", "review", "ann", ts("2020-05-02T00:00"))
    add_event(conn, "C1", "I2", "comment", "bo", ts("2020-07-02T00:00"))
    if extra:
        add_item(conn, "I3", 3, "issue", "dee", ts("2021-08-01T00:00"))
    conn.commit()


@contextlib.contextmanager
def serve(directory: Path):
    """Serve a folder on localhost and yield its base URL."""

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextlib.contextmanager
def served_site():
    """Build the fixture site into a temp dir, serve it, and yield its base URL."""
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        for name in [*PROJECTS, UNLISTED]:
            (tmp / f"{name}.toml").write_text(
                f'data_dir = "{(tmp / "data").as_posix()}"\n'
                f'[repo]\ngithub = "org/{name}"\nlabel = "Org {name}"\n'
            )
            conn = storage.connect(config.load(tmp / f"{name}.toml").db_path)
            fill(conn, extra=name == PROJECTS[0])
            conn.close()
        names = ", ".join(f'"{p}.toml"' for p in PROJECTS)
        (tmp / "deploy.toml").write_text(
            f'projects = [{names}]\nindex = "{PROJECTS[0]}.toml"\n'
        )
        site = tmp / "site"
        deploy.build(deploy.load_list(tmp / "deploy.toml"), site)
        with serve(site) as url:
            yield url
