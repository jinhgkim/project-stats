"""Pieces of work as cleaned text, and the periods (years, release cycles) they
fall in.

Each document is one piece of work: a PR, an issue, or a commit that isn't
linked to a PR (linked commits are represented by their PR). Cleaning removes
code, logs, links, trailers, and template boilerplate, so only the
description of the work is left.
"""

import re
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.S)
HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
URL = re.compile(r"https?://\S+")
MENTION = re.compile(r"(?<![\w@])@[\w-]+")
ISSUE_REF = re.compile(r"(?<![\w&])#\d+\b")
CHECKBOX = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*")
TRAILER = re.compile(r"^[A-Za-z]+(?:-[A-Za-z]+)+:\s")  # Signed-off-by: ...
PR_SUFFIX = re.compile(r"\(#(\d+)\)\s*$")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_MARKS = re.compile(r"[*_`>#~|]+")
FIELD = re.compile(r"^[-* ]*([a-z][^:]{0,40}):\s*(\S.*)$")


@dataclass
class Document:
    source: str  # "pr", "issue", or "commit"
    ref: str  # "pr#12", "issue#3", or a short commit sha
    ts: int  # when the work started: PR/issue opened, commit authored
    title: str
    body: str


@dataclass(frozen=True)
class Period:
    label: str  # "2024", or "3.2 cycle" for the work released in 3.2
    start: int | None  # None: open-ended
    end: int | None
    partial: bool = False  # still in progress


def load_documents(conn: sqlite3.Connection) -> list[Document]:
    docs = []
    pr_numbers, merge_shas = set(), set()
    for kind, number, title, body, created, sha in conn.execute(
        "SELECT kind, number, title, body, created_at, merge_commit_sha FROM live_items"
    ):
        docs.append(Document(kind, f"{kind}#{number}", created, title, body))
        if kind == "pr":
            pr_numbers.add(number)
            if sha:
                merge_shas.add(sha)
    for sha, subject, body, ts in conn.execute(
        "SELECT sha, subject, body, authored_at FROM commits"
    ):
        m = PR_SUFFIX.search(subject)
        if sha in merge_shas or (m and int(m.group(1)) in pr_numbers):
            continue
        docs.append(Document("commit", sha[:10], ts, subject, body))
    return docs


def _year_start(year: int) -> int:
    return int(datetime(year, 1, 1, tzinfo=UTC).timestamp())


def year_periods(docs: list[Document]) -> list[Period]:
    """Calendar years from the first document's to the last's (UTC)."""
    years = [datetime.fromtimestamp(d.ts, UTC).year for d in docs]
    first, last = min(years), max(years)
    return [
        Period(str(y), _year_start(y), _year_start(y + 1), partial=y == last)
        for y in range(first, last + 1)
    ]


def release_periods(releases) -> list[Period]:
    """Cycles between releases, each labeled by the release it led to.

    Work before the first release belongs to that release's cycle; work after
    the latest release is the cycle in progress.
    """
    rs = sorted(releases, key=lambda r: r.released_at)
    if not rs:
        raise ValueError("no releases found; check [releases] tag_pattern")
    periods = [Period(f"{rs[0].version} cycle", None, rs[0].released_at)]
    for before, release in zip(rs, rs[1:], strict=False):
        periods.append(
            Period(f"{release.version} cycle", before.released_at, release.released_at)
        )
    periods.append(
        Period(f"after {rs[-1].version}", rs[-1].released_at, None, partial=True)
    )
    return periods


def assign(docs: list[Document], periods: list[Period]) -> list[int]:
    """Index of the period each document falls in."""
    starts = [p.start for p in periods[1:]]
    return [bisect_right(starts, d.ts) for d in docs]


def _line_keys(line: str) -> set[str]:
    """Comparison keys for boilerplate: the line ignoring checkboxes, "(N/A)",
    markdown, and case; plus "field:<label>" for short "Label: value" lines,
    whose values differ (e.g. "OIIO branch/version: 2.1.17")."""
    text = CHECKBOX.sub("", line).lower()
    text = MD_LINK.sub(r"\1", text.replace("(n/a)", " "))
    text = " ".join(MD_MARKS.sub(" ", text).split())
    if not text:
        return set()
    keys = {text}
    m = FIELD.match(text)
    if m and len(m.group(2)) <= 40:
        keys.add(f"field:{m.group(1).strip()}")
    return keys


def _line_counts(bodies: list[str]) -> Counter:
    counts = Counter()
    for body in bodies:
        counts.update({k for line in body.splitlines() for k in _line_keys(line)})
    return counts


def find_boilerplate(
    docs: Iterable[Document],
    share: float = 0.01,
    min_count: int = 20,
    year_share: float = 0.05,
    year_min_count: int = 5,
) -> set[str]:
    """Lines repeated across many documents of one source, e.g. a PR template.

    A line counts if it is in `share` of all the documents (and `min_count`),
    or in `year_share` of any single year's (and `year_min_count`), so a
    template used for only a few years is caught too.
    """
    docs = list(docs)
    found = set()
    counts = _line_counts([d.body for d in docs])
    floor = max(min_count, share * len(docs))
    found |= {line for line, n in counts.items() if n >= floor}
    by_year = defaultdict(list)
    for d in docs:
        by_year[datetime.fromtimestamp(d.ts, UTC).year].append(d.body)
    for bodies in by_year.values():
        floor = max(year_min_count, year_share * len(bodies))
        found |= {line for line, n in _line_counts(bodies).items() if n >= floor}
    return found


def clean(title: str, body: str, boilerplate: set[str] = frozenset()) -> str:
    """Title and body with code, links, trailers, and boilerplate removed.

    The title is kept whole, including a "fix(exr):" style prefix, since the
    prefix says which part of the project the work is about.
    """
    body = HTML_COMMENT.sub(" ", FENCED_CODE.sub(" ", body))
    lines = [title]
    for line in body.splitlines():
        if TRAILER.match(line) or _line_keys(line) & boilerplate:
            continue
        lines.append(CHECKBOX.sub("", line))
    text = "\n".join(lines)
    for pattern in (URL, MENTION, ISSUE_REF):
        text = pattern.sub(" ", text)
    return text


def clean_documents(docs: list[Document]) -> list[str]:
    """Cleaned text of each document, with boilerplate found per source."""
    by_source = defaultdict(list)
    for doc in docs:
        by_source[doc.source].append(doc)
    boilerplate = {s: find_boilerplate(group) for s, group in by_source.items()}
    return [clean(d.title, d.body, boilerplate[d.source]) for d in docs]
