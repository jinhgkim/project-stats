"""Theme trends: how much work and discussion each theme gets per period.

Activity takes the themes of the document it belongs to: a PR's reviews and
comments, and commits linked to the PR, all count toward the PR's themes.
Shares are taken among activity on tagged documents only, and periods that
are mostly untagged get no shares or trends, so missing tags never look like
a theme dropping to zero.
"""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from projstats.documents import Document, Period, assign, commit_ref, period_indexes
from projstats.retention import Activity

CODE_KINDS = {"commit"}  # every other activity kind counts as discussion


@dataclass
class ThemeStat:
    theme_id: str
    name: str
    docs: int = 0  # tagged documents started in the period
    code: int = 0
    discussion: int = 0
    people: int = 0
    share: float | None = None  # of activity on tagged documents; None if not covered


@dataclass
class PeriodTrends:
    period: Period
    docs: int  # all documents started in the period
    tagged: int
    covered: bool  # enough documents tagged for shares to mean something
    activity: int  # activity on tagged documents
    themes: list[ThemeStat] = field(default_factory=list)  # most activity first
    # Themes whose first tagged document is here. Only known when an earlier
    # period is covered; otherwise every theme would look new.
    new_themes: list[str] = field(default_factory=list)
    new_known: bool = False


@dataclass
class Trend:
    theme_id: str
    name: str
    label: str  # "rising", "fading", "steady", or "too few"
    recent_share: float
    earlier_share: float
    docs: int  # documents in the compared periods


@dataclass
class Contributor:
    person: str
    code: int
    discussion: int


@dataclass
class TrendReport:
    periods: list[PeriodTrends]
    recent: int | None  # period index the trends compare against earlier ones
    earlier: list[int]
    trends: list[Trend]
    contributors: dict[str, list[Contributor]]  # theme id -> top people


def load_doc_themes(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """doc_ref -> ids of its (live) themes."""
    out: dict[str, set[str]] = defaultdict(set)
    for ref, theme_id in conn.execute(
        "SELECT d.doc_ref, d.theme_id FROM doc_themes d JOIN themes t "
        "ON t.id = d.theme_id WHERE t.merged_into IS NULL"
    ):
        out[ref].add(theme_id)
    return dict(out)


def load_tagged(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT doc_ref FROM doc_tagging")}


def load_theme_names(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT id, name FROM themes WHERE merged_into IS NULL"))


def doc_ref_of(activity: Activity, links: dict[str, str]) -> str:
    """The document an activity belongs to."""
    if activity.kind == "commit":
        return links.get(activity.item) or commit_ref(activity.item)
    return activity.item


def analyze(
    docs: list[Document],
    activity: list[Activity],
    periods: list[Period],
    doc_themes: dict[str, set[str]],
    tagged: set[str],
    names: dict[str, str],
    links: dict[str, str],
    person_names: dict[str, str] | None = None,
    skip_in_progress: bool = False,
    coverage: float = 0.5,
    rise: float = 1.5,
    fade: float = 0.67,
    min_docs: int = 5,
    top: int = 5,
) -> TrendReport:
    """Per-period theme stats, rising/fading themes, and top contributors.

    Trends compare the last covered period with all earlier covered ones
    combined. With `skip_in_progress` (release cycles), an in-progress last
    period is left out of that comparison.
    """
    person_names = person_names or {}
    n = len(periods)
    docs_in = [0] * n
    tagged_in = [0] * n
    theme_docs: dict[str, Counter] = defaultdict(Counter)
    first_doc: dict[str, tuple[int, int]] = {}  # theme -> (ts, period)
    for doc, p in zip(docs, assign(docs, periods), strict=True):
        docs_in[p] += 1
        if doc.ref not in tagged:
            continue
        tagged_in[p] += 1
        for theme_id in doc_themes.get(doc.ref, ()):
            theme_docs[theme_id][p] += 1
            if theme_id not in first_doc or doc.ts < first_doc[theme_id][0]:
                first_doc[theme_id] = (doc.ts, p)

    activity_in = [0] * n  # on tagged documents
    code: dict[str, Counter] = defaultdict(Counter)
    discussion: dict[str, Counter] = defaultdict(Counter)
    people: dict[str, dict[int, set]] = defaultdict(lambda: defaultdict(set))
    by_person: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for a, p in zip(
        activity, period_indexes([a.ts for a in activity], periods), strict=True
    ):
        ref = doc_ref_of(a, links)
        if ref not in tagged:
            continue
        activity_in[p] += 1
        side = "code" if a.kind in CODE_KINDS else "discussion"
        for theme_id in doc_themes.get(ref, ()):
            (code if side == "code" else discussion)[theme_id][p] += 1
            people[theme_id][p].add(a.person)
            by_person[theme_id][a.person][side] += 1

    covered = [
        bool(docs_in[p]) and tagged_in[p] / docs_in[p] >= coverage for p in range(n)
    ]
    theme_ids = sorted(set(theme_docs) | set(code) | set(discussion))

    out_periods = []
    for p, period in enumerate(periods):
        stats = []
        for theme_id in theme_ids:
            c, d = code[theme_id][p], discussion[theme_id][p]
            if not (c or d or theme_docs[theme_id][p]):
                continue
            share = (c + d) / activity_in[p] if covered[p] and activity_in[p] else None
            stats.append(
                ThemeStat(
                    theme_id,
                    names.get(theme_id, theme_id),
                    theme_docs[theme_id][p],
                    c,
                    d,
                    len(people[theme_id][p]),
                    share,
                )
            )
        stats.sort(key=lambda s: (-(s.code + s.discussion), s.name))
        new_known = any(covered[:p])
        new = sorted(
            names.get(t, t) for t, (_, first_p) in first_doc.items() if first_p == p
        )
        out_periods.append(
            PeriodTrends(
                period,
                docs_in[p],
                tagged_in[p],
                covered[p],
                activity_in[p],
                stats,
                new if new_known else [],
                new_known,
            )
        )

    candidates = [
        p
        for p in range(n)
        if covered[p] and not (skip_in_progress and periods[p].partial)
    ]
    recent = candidates[-1] if candidates else None
    earlier = candidates[:-1]
    trends = []
    if recent is not None and earlier:
        base = sum(activity_in[p] for p in earlier)
        for theme_id in theme_ids:
            total = code[theme_id][recent] + discussion[theme_id][recent]
            before = sum(code[theme_id][p] + discussion[theme_id][p] for p in earlier)
            recent_share = total / activity_in[recent] if activity_in[recent] else 0
            earlier_share = before / base if base else 0
            n_docs = sum(theme_docs[theme_id][p] for p in [*earlier, recent])
            if n_docs < min_docs:
                label = "too few"
            elif earlier_share == 0:
                label = "rising" if recent_share > 0 else "steady"
            elif recent_share >= rise * earlier_share:
                label = "rising"
            elif recent_share <= fade * earlier_share:
                label = "fading"
            else:
                label = "steady"
            trends.append(
                Trend(
                    theme_id,
                    names.get(theme_id, theme_id),
                    label,
                    recent_share,
                    earlier_share,
                    n_docs,
                )
            )
        order = {"rising": 0, "fading": 1, "steady": 2, "too few": 3}
        trends.sort(key=lambda t: (order[t.label], -t.recent_share, t.name))

    contributors = {}
    for theme_id, counts in by_person.items():
        ranked = sorted(
            counts.items(),
            key=lambda kv: (
                -(kv[1]["code"] + kv[1]["discussion"]),
                person_names.get(kv[0], kv[0]),
            ),
        )
        contributors[theme_id] = [
            Contributor(person, c["code"], c["discussion"])
            for person, c in ranked[:top]
        ]

    return TrendReport(out_periods, recent, earlier, trends, contributors)
