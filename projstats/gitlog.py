"""Mirror a repository's history locally and import its commits."""

import re
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from projstats.storage import get_state, set_state

SEP = "\x1f"
TRAILER_SEP = "\x1d"
# Body goes last so a stray separator inside it can't shift the other fields.
FIELDS = (
    "%H",
    "%at",
    "%ct",
    "%an",
    "%ae",
    "%s",
    "%(trailers:key=Co-authored-by,valueonly,separator=%x1d)",
    "%b",
)
IDENT = re.compile(r"^(.*?)\s*<([^<>]*)>\s*$")

Ident = tuple[str, str]  # (name, email)


@dataclass
class Commit:
    sha: str
    authored_at: int
    committed_at: int
    author: Ident
    subject: str
    body: str
    coauthors: list[Ident] = field(default_factory=list)


@dataclass
class ImportStats:
    head: str
    new: int = 0
    total: int = 0
    rewritten: bool = False
    remapped: bool = False


def git(repo: Path, *args: str, stdin: str | None = None, check: bool = True):
    # Old commits can hold bytes that aren't valid UTF-8.
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def sync_clone(url: str, path: Path, blobless: bool = True) -> str:
    """Clone a bare copy of `url` at `path`, or fetch new history into it."""
    if (path / "HEAD").exists():
        # `clone --bare` sets no fetch refspec, so name the branches explicitly.
        git(path, "fetch", "--prune", "--quiet", "origin", "+refs/heads/*:refs/heads/*")
        return "updated"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--bare", "--quiet"]
    if blobless:
        cmd.append("--filter=blob:none")
    subprocess.run([*cmd, url, str(path)], capture_output=True, text=True, check=True)
    return "cloned"


def _ident(text: str) -> Ident | None:
    m = IDENT.match(text.strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def read_commits(repo: Path, rev_range: str = "HEAD") -> Iterator[Commit]:
    """Non-merge commits in `rev_range`, newest first, with raw identities."""
    fmt = SEP.join(FIELDS)
    out = git(repo, "log", "--no-merges", "-z", f"--format={fmt}", rev_range).stdout
    for record in out.split("\0"):
        if not record:
            continue
        sha, at, ct, name, email, subject, trailers, body = record.split(SEP, 7)
        coauthors = [
            ident
            for t in trailers.split(TRAILER_SEP)
            if (ident := _ident(t)) and ident[1]
        ]
        yield Commit(
            sha, int(at), int(ct), (name, email), subject, body.strip(), coauthors
        )


def map_identities(repo: Path, idents: Iterable[Ident]) -> dict[Ident, Ident]:
    """Apply the repository's .mailmap to raw identities in one git call."""
    idents = sorted({i for i in idents if i[1]})
    if not idents:
        return {}
    lines = "".join(f"{name} <{email}>".strip() + "\n" for name, email in idents)
    out = git(repo, "check-mailmap", "--stdin", stdin=lines).stdout.splitlines()
    mapped = {}
    for raw, line in zip(idents, out, strict=True):
        name, email = _ident(line) or raw
        mapped[raw] = (name or raw[0], email or raw[1])
    return mapped


def mailmap_blob(repo: Path) -> str:
    """Object id of HEAD's .mailmap, or "" if there is none."""
    result = git(repo, "rev-parse", "--verify", "--quiet", "HEAD:.mailmap", check=False)
    return result.stdout.strip()


def _resolve(mapping: dict[Ident, Ident], ident: Ident) -> Ident:
    return mapping.get(ident, ident)


def import_commits(conn: sqlite3.Connection, repo: Path) -> ImportStats:
    """Import commits added since the last run.

    Everything is reimported if the last seen HEAD is no longer in history
    (a force-push). If .mailmap changed, stored identities are re-mapped.
    """
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    last = get_state(conn, "git.head")
    full = (
        last is None
        or git(repo, "merge-base", "--is-ancestor", last, head, check=False).returncode
        != 0
    )
    commits = list(read_commits(repo, "HEAD" if full else f"{last}..HEAD"))
    mailmap = mailmap_blob(repo)
    remap = not full and get_state(conn, "git.mailmap") != mailmap

    idents = {c.author for c in commits} | {i for c in commits for i in c.coauthors}
    if remap:
        idents |= {
            (r["raw_name"], r["raw_email"])
            for table in ("commits", "commit_coauthors")
            for r in conn.execute(f"SELECT DISTINCT raw_name, raw_email FROM {table}")
        }
    mapping = map_identities(repo, idents)

    with conn:
        if full:
            conn.execute("DELETE FROM commit_coauthors")
            conn.execute("DELETE FROM commits")
        conn.executemany(
            "INSERT OR REPLACE INTO commits (sha, authored_at, committed_at, "
            "author_name, author_email, raw_name, raw_email, subject, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    c.sha,
                    c.authored_at,
                    c.committed_at,
                    *_resolve(mapping, c.author),
                    *c.author,
                    c.subject,
                    c.body,
                )
                for c in commits
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO commit_coauthors "
            "(sha, name, email, raw_name, raw_email) VALUES (?, ?, ?, ?, ?)",
            [
                (c.sha, *_resolve(mapping, co), *co)
                for c in commits
                for co in c.coauthors
            ],
        )
        if remap:
            for table, name, email in (
                ("commits", "author_name", "author_email"),
                ("commit_coauthors", "name", "email"),
            ):
                conn.executemany(
                    f"UPDATE {table} SET {name} = ?, {email} = ? "
                    "WHERE raw_name = ? AND raw_email = ?",
                    [(*new, *raw) for raw, new in mapping.items()],
                )
        set_state(conn, "git.head", head)
        set_state(conn, "git.mailmap", mailmap)

    total = conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0]
    return ImportStats(head, len(commits), total, full and last is not None, remap)
