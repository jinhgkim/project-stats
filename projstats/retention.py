"""Contributor retention: activity per period, per-person cadence, cohorts.

All times are UTC. Periods are calendar months, quarters (Q1 = Jan-Mar), or
years. "Returning" means the person's first activity in a period comes at
least `return_gap_days` after their previous activity, which gives the same
answer at every period size.
"""

import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import groupby

from projstats.config import RetentionConfig
from projstats.identity import People

DAY = 86_400
PERIOD_MONTHS = {"month": 1, "quarter": 3, "year": 12}
COHORT_OFFSETS = (1, 2, 5)
KINDS = ("commit", "pr", "review", "issue", "comment")


@dataclass(frozen=True)
class Activity:
    person: str  # Person.key
    ts: int
    kind: str  # one of KINDS
    item: str  # commit sha, or "pr#123" / "issue#45" (also for reviews, comments)


@dataclass
class PeriodRow:
    key: int
    label: str
    start: int | None  # None: open-ended (first release cycle)
    end: int | None  # exclusive; None: open-ended (cycle in progress)
    active: int = 0
    new: int = 0
    returning: int = 0
    continuing: int = 0
    last_seen: int | None = None  # None while those people may still come back
    activity: int = 0
    partial: bool = False


@dataclass
class PersonStats:
    person: str
    first: int
    last: int
    activity: int
    months: int
    quarters: int
    years: tuple[int, ...]
    longest_gap_days: int
    returns: int
    segment: str  # by share of the activity given (see segments())
    current: bool  # active within return_gap_days of the end of the data


@dataclass
class Cohort:
    year: int
    size: int
    one_time: int
    # offset (years after first) -> people active that year; None if not complete
    active_after: dict[int, int | None] = field(default_factory=dict)


def load_commit_activity(conn: sqlite3.Connection, people: People) -> list[Activity]:
    """One activity per (person, commit), for authors and co-authors alike."""
    rows = conn.execute(
        """
        SELECT sha, authored_at, author_email FROM commits
        UNION ALL
        SELECT c.sha, c.authored_at, a.email
        FROM commit_coauthors a JOIN commits c USING (sha)
        """
    )
    seen, out = set(), []
    for sha, ts, email in rows:
        person = people.by_email.get(email.lower())
        if person is None or (person.key, sha) in seen:
            continue
        seen.add((person.key, sha))
        out.append(Activity(person.key, ts, "commit", sha))
    out.sort(key=lambda a: (a.ts, a.person, a.item))
    return out


def load_activity(
    conn: sqlite3.Connection, people: People, kinds: Iterable[str] | None = None
) -> list[Activity]:
    """Activity of every kind (or just `kinds`), oldest first.

    PRs and issues count when opened, reviews when submitted, comments when
    posted. Vanished GitHub rows, ghosts, and bots are left out.
    """
    kinds = set(KINDS if kinds is None else kinds)
    unknown = kinds - set(KINDS)
    if unknown:
        raise ValueError(f"unknown activity kind(s): {', '.join(sorted(unknown))}")
    out = load_commit_activity(conn, people) if "commit" in kinds else []
    rows = conn.execute(
        """
        SELECT kind, author_login, created_at, kind || '#' || number FROM live_items
        UNION ALL
        SELECT e.kind, e.author_login, e.created_at, i.kind || '#' || i.number
        FROM live_events e JOIN items i ON i.id = e.item_id
        """
    )
    for kind, login, ts, item in rows:
        if kind not in kinds or login is None:
            continue
        person = people.by_login.get(login.casefold())
        if person is not None:
            out.append(Activity(person.key, ts, kind, item))
    out.sort(key=lambda a: (a.ts, a.person, a.kind, a.item))
    return out


def exclude_items(
    activity: list[Activity], numbers: Iterable[int], links: dict[str, str]
) -> list[Activity]:
    """Drop activity on the given PR or issue numbers, including commits that
    `links` (sha -> "pr#N", from documents.commit_links) ties to those PRs."""
    refs = {f"{kind}#{n}" for n in numbers for kind in ("pr", "issue")}
    if not refs:
        return activity
    return [a for a in activity if links.get(a.item, a.item) not in refs]


def _month_index(ts: int) -> int:
    d = datetime.fromtimestamp(ts, UTC)
    return d.year * 12 + d.month - 1


def _month_start(index: int) -> int:
    year, month = divmod(index, 12)
    return int(datetime(year, month + 1, 1, tzinfo=UTC).timestamp())


def period_key(ts: int, period: str) -> int:
    """Months since year 0 divided into periods: comparable, consecutive ints."""
    return _month_index(ts) // PERIOD_MONTHS[period]


def period_bounds(key: int, period: str) -> tuple[int, int]:
    n = PERIOD_MONTHS[period]
    return _month_start(key * n), _month_start((key + 1) * n)


def period_label(key: int, period: str) -> str:
    if period == "month":
        return f"{key // 12}-{key % 12 + 1:02d}"
    if period == "quarter":
        return f"{key // 4} Q{key % 4 + 1}"
    return str(key)


def _by_person(activity: list[Activity]) -> dict[str, list[int]]:
    times = defaultdict(list)
    for a in activity:
        times[a.person].append(a.ts)
    return {p: sorted(ts) for p, ts in times.items()}


def _scheme(period) -> tuple[Callable, Callable, Callable]:
    """(key of a timestamp, bounds of a key, label of a key) for a period."""
    if isinstance(period, str):
        return (
            lambda ts: period_key(ts, period),
            lambda k: period_bounds(k, period),
            lambda k: period_label(k, period),
        )
    starts = [c.start for c in period[1:]]
    return (
        lambda ts: bisect_right(starts, ts),
        lambda k: (period[k].start, period[k].end),
        lambda k: period[k].label,
    )


def period_counts(
    activity: list[Activity], period: str | Sequence, return_gap_days: int
) -> list[PeriodRow]:
    """New / returning / continuing / last-seen people for every period.

    `period` is "month", "quarter", "year", or a list of cycles with label,
    start, and end (start None for the first, end None for the last), such as
    documents.release_periods().
    """
    if not activity:
        return []
    key_of, bounds_of, label_of = _scheme(period)
    gap = return_gap_days * DAY
    data_end = max(a.ts for a in activity)
    keys = [key_of(a.ts) for a in activity]
    rows = {}
    for key in range(min(keys), max(keys) + 1):
        start, end = bounds_of(key)
        rows[key] = PeriodRow(key, label_of(key), start, end)
    rows[max(keys)].partial = True

    last_seen = Counter()
    for times in _by_person(activity).values():
        prev = None
        for key, group in groupby(times, key=key_of):
            group = list(group)
            row = rows[key]
            row.active += 1
            row.activity += len(group)
            if prev is None:
                row.new += 1
            elif group[0] - prev >= gap:
                row.returning += 1
            else:
                row.continuing += 1
            prev = group[-1]
        last_seen[key_of(times[-1])] += 1

    for row in rows.values():
        if row.end is not None and data_end - row.end >= gap:
            row.last_seen = last_seen[row.key]
    return list(rows.values())


def segments(counts: dict[str, int], cfg: RetentionConfig) -> dict[str, str]:
    """Segment per person from their activity counts.

    One-time: exactly one activity. Otherwise, ranked by activity, core is the
    top group that together reaches `core_share` of all activity and regular
    the next group up to `regular_share`; people tied with the one who
    crosses a cutoff join that group. Everyone else is casual.
    """
    total = sum(counts.values())
    ranked = sorted(counts.values(), reverse=True)

    def cutoff(share: float) -> int:
        run = 0
        for n in ranked:
            run += n
            if run >= share * total:
                return n
        return 0

    core_min, regular_min = cutoff(cfg.core_share), cutoff(cfg.regular_share)
    out = {}
    for person, n in counts.items():
        if n == 1:
            out[person] = "one-time"
        elif n >= core_min:
            out[person] = "core"
        elif n >= regular_min:
            out[person] = "regular"
        else:
            out[person] = "casual"
    return out


def person_stats(activity: list[Activity], cfg: RetentionConfig) -> list[PersonStats]:
    """Cadence per person, most active first."""
    gap = cfg.return_gap_days * DAY
    data_end = max((a.ts for a in activity), default=0)
    by_person = _by_person(activity)
    segment_of = segments({p: len(ts) for p, ts in by_person.items()}, cfg)
    out = []
    for person, times in by_person.items():
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        quarters = len({period_key(t, "quarter") for t in times})
        out.append(
            PersonStats(
                person=person,
                first=times[0],
                last=times[-1],
                activity=len(times),
                months=len({period_key(t, "month") for t in times}),
                quarters=quarters,
                years=tuple(sorted({period_key(t, "year") for t in times})),
                longest_gap_days=max(gaps, default=0) // DAY,
                returns=sum(g >= gap for g in gaps),
                segment=segment_of[person],
                current=data_end - times[-1] < gap,
            )
        )
    out.sort(key=lambda s: (-s.activity, s.person))
    return out


def cohorts(stats: list[PersonStats], data_end: int) -> list[Cohort]:
    """Groups by first-activity year; how many were active N years later.

    Only complete calendar years count, so years at or after the year of
    `data_end` show as None.
    """
    last_complete = period_key(data_end, "year") - 1
    groups = defaultdict(list)
    for s in stats:
        groups[s.years[0]].append(s)
    out = []
    for year in sorted(groups):
        members = groups[year]
        cohort = Cohort(
            year, len(members), sum(s.segment == "one-time" for s in members)
        )
        for n in COHORT_OFFSETS:
            target = year + n
            cohort.active_after[n] = (
                None
                if target > last_complete
                else sum(target in s.years for s in members)
            )
        out.append(cohort)
    return out
