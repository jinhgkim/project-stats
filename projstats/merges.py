"""Time to merge: how long PRs took from opened to merged, per period.

Counted in whole UTC days, as the page counts: a PR opened and merged on
the same day took 0 days. The PRs are the "pr" rows of the activity (opened
by people, not bots, and not excluded), and each one falls in the period it
was merged in, so recent periods aren't missing slow PRs that are still open.
"""

import sqlite3
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from projstats.retention import Activity, period_scheme

DAY = 86_400
# Each bucket's name and the fewest whole days a PR in it took.
BUCKETS = (("same day", 0), ("1-6 days", 1), ("7-29 days", 7), ("30+ days", 30))


@dataclass
class MergeRow:
    key: int
    label: str
    counts: list[int]  # PRs per bucket, in BUCKETS order
    median: float | None  # days; None when no PR was merged in the period
    partial: bool  # holds the end of the data, so it may still grow


def load_merged(conn: sqlite3.Connection) -> dict[str, int]:
    """When each merged PR was merged, by its item ("pr#12")."""
    return {
        f"pr#{number}": merged_at
        for number, merged_at in conn.execute(
            "SELECT number, merged_at FROM live_items"
            " WHERE kind = 'pr' AND merged_at IS NOT NULL"
        )
    }


def bucket(days: int) -> int:
    """Index in BUCKETS for a PR that took `days` whole days."""
    return sum(1 for _, fewest in BUCKETS[1:] if days >= fewest)


def merge_counts(
    activity: Iterable[Activity],
    merged: dict[str, int],
    period: str | Sequence,
    data_end: int,
) -> list[MergeRow]:
    """PRs merged per period, by bucket, with the median days.

    `period` is "month", "quarter", "year", or a list of release cycles, as
    for retention.period_counts. Periods between the first and the last
    merge are all listed, empty ones included.
    """
    key_of, _, label_of = period_scheme(period)
    days_by_key: dict[int, list[int]] = defaultdict(list)
    for a in activity:
        if a.kind == "pr" and a.item in merged:
            done = merged[a.item]
            days_by_key[key_of(done)].append(done // DAY - a.ts // DAY)
    if not days_by_key:
        return []
    end_key = key_of(data_end)
    rows = []
    for key in range(min(days_by_key), max(days_by_key) + 1):
        days = days_by_key.get(key, [])
        counts = [0] * len(BUCKETS)
        for d in days:
            counts[bucket(d)] += 1
        median = statistics.median(days) if days else None
        rows.append(MergeRow(key, label_of(key), counts, median, key == end_key))
    return rows
