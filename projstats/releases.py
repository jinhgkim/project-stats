"""Releases from version tags: one per major.minor version, dated by its tag."""

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from projstats.gitlog import git


@dataclass(frozen=True)
class Release:
    version: str  # "major.minor"
    tag: str
    released_at: int


def find_releases(tags: Iterable[tuple[str, int]], pattern: str) -> list[Release]:
    """Each major.minor version's earliest final tag, oldest release first.

    `pattern` must fully match final release tags (not betas or RCs) and
    capture major, minor, patch, and optionally a fourth number.
    """
    regex = re.compile(pattern)
    best: dict[tuple[int, int], tuple[tuple[int, int, int], str]] = {}
    for name, ts in tags:
        m = regex.fullmatch(name)
        if not m:
            continue
        major, minor, patch = (int(g) for g in m.groups()[:3])
        extra = m.groups()[3] if len(m.groups()) > 3 else None
        rank = (patch, int(extra or 0), ts)
        key = (major, minor)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, name)
    releases = [
        Release(f"{major}.{minor}", name, rank[2])
        for (major, minor), (rank, name) in best.items()
    ]
    return sorted(releases, key=lambda r: (r.released_at, r.version))


def import_releases(conn: sqlite3.Connection, repo: Path, pattern: str) -> list:
    """Rebuild the releases table from the clone's tags."""
    out = git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)%09%(creatordate:unix)",
        "refs/tags",
    ).stdout
    tags = [
        (name, int(ts))
        for line in out.splitlines()
        for name, _, ts in [line.partition("\t")]
        if ts.strip()
    ]
    releases = find_releases(tags, pattern)
    with conn:
        conn.execute("DELETE FROM releases")
        conn.executemany(
            "INSERT INTO releases (version, tag, released_at) VALUES (?, ?, ?)",
            [(r.version, r.tag, r.released_at) for r in releases],
        )
    return releases


def load_releases(conn: sqlite3.Connection) -> list[Release]:
    rows = conn.execute(
        "SELECT version, tag, released_at FROM releases ORDER BY released_at, version"
    )
    return [Release(*row) for row in rows]
