"""Compact JSON for the page: people, documents, activity, themes, releases,
and reference numbers from the tested Python code for the page's #check mode.

Large parts are columnar (one array per field) and use indexes instead of
repeated strings. Times are whole days since 1970-01-01 (UTC). Emails are
left out, including ones written in titles ("Patch by: Name <email>"), so the
page can be shared.
"""

import dataclasses
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from projstats import documents, identity, releases, retention, trends
from projstats.config import Config

VERSION = 1
DAY = 86_400
EMAIL = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
# (kinds or None for all, period) combinations checked by the page's #check.
# "release" is release cycles, and is skipped when there are no releases.
REFERENCE_PERIOD_COUNTS = [
    (None, "year"),
    (["commit"], "quarter"),
    (["review"], "month"),
    (["commit", "pr", "issue"], "release"),
]
REFERENCE_SEGMENTS = [None, ["commit"]]


def day(ts: int) -> int:
    return ts // DAY


def _day_start(ts: int) -> int:
    return ts - ts % DAY


def redact(text: str) -> str:
    """Replace email addresses; "pkg@2.3.1" style version pins are kept."""
    return EMAIL.sub("[email]", text)


def _short_ref(doc: documents.Document) -> str:
    return doc.ref.split("#", 1)[1] if "#" in doc.ref else doc.ref


def _people_by_login(people: list, logins: list[str]) -> list[int]:
    """Person indexes for `logins` (any of a person's logins, any case)."""
    out = []
    for login in logins:
        want = login.casefold()
        found = [
            i for i, p in enumerate(people) if want in {x.casefold() for x in p.logins}
        ]
        if not found:
            raise ValueError(f"[people] leave_out_option: no one has login {login!r}")
        out.extend(i for i in found if i not in out)
    return out


def build(conn: sqlite3.Connection, cfg: Config, generated: str | None = None) -> dict:
    people = identity.load_people(conn, cfg.people.bots)
    person_index = {p.key: i for i, p in enumerate(people.people)}
    docs = sorted(documents.load_documents(conn), key=lambda d: (d.ts, d.ref))
    doc_index = {d.ref: i for i, d in enumerate(docs)}
    links = documents.commit_links(conn)
    activity = retention.exclude_items(
        retention.load_activity(conn, people), cfg.activity.exclude_items, links
    )
    kinds = list(retention.KINDS)
    kind_index = {k: i for i, k in enumerate(kinds)}
    rels = releases.load_releases(conn)

    theme_names = trends.load_theme_names(conn)
    theme_ids = sorted(theme_names, key=lambda t: theme_names[t].casefold())
    theme_index = {t: i for i, t in enumerate(theme_ids)}
    doc_themes = trends.load_doc_themes(conn)
    tagged = trends.load_tagged(conn)
    pairs = sorted(
        (doc_index[ref], theme_index[t])
        for ref, ids in doc_themes.items()
        if ref in doc_index
        for t in ids
    )

    optional = _people_by_login(people.people, cfg.people.leave_out_option)

    sources = {}
    for a in activity:
        sources[a.kind] = min(sources.get(a.kind, a.ts), a.ts)

    data = {
        "version": VERSION,
        "project": {
            "github": cfg.repo.github,
            "generated": generated or datetime.now(UTC).strftime("%Y-%m-%d"),
            "data_end": day(max(a.ts for a in activity)) if activity else None,
            "excluded_items": sorted(cfg.activity.exclude_items),
            "leave_out_option": optional,
        },
        "settings": dataclasses.asdict(cfg.retention),
        "kinds": kinds,
        "people": {
            "name": [p.name for p in people.people],
            "login": [min(p.logins) if p.logins else "" for p in people.people],
        },
        "docs": {
            "source": [d.source for d in docs],
            "ref": [_short_ref(d) for d in docs],
            "title": [redact(d.title) for d in docs],
            "day": [day(d.ts) for d in docs],
        },
        "activity": {
            "person": [person_index[a.person] for a in activity],
            "day": [day(a.ts) for a in activity],
            "kind": [kind_index[a.kind] for a in activity],
            "doc": [doc_index.get(trends.doc_ref_of(a, links), -1) for a in activity],
        },
        "themes": {
            "name": [theme_names[t] for t in theme_ids],
            "doc": [d for d, _ in pairs],
            "theme": [t for _, t in pairs],
            "tagged": sorted(doc_index[r] for r in tagged if r in doc_index),
        },
        "releases": {
            "version": [r.version for r in rels],
            "tag": [r.tag for r in rels],
            "day": [day(r.released_at) for r in rels],
        },
        "sources": {k: day(ts) for k, ts in sorted(sources.items())},
    }
    data["reference"] = reference(cfg, people, docs, activity, rels, links, conn)
    return data


def reference(cfg, people, docs, activity, rels, links, conn) -> dict:
    """Python's numbers for a few fixed filters, computed at day precision
    (as the page works) so the two can match exactly."""
    r = cfg.retention
    by_day = [dataclasses.replace(a, ts=_day_start(a.ts)) for a in activity]

    def subset(kinds):
        return by_day if kinds is None else [a for a in by_day if a.kind in kinds]

    day_rels = [
        dataclasses.replace(x, released_at=_day_start(x.released_at)) for x in rels
    ]
    period_counts = []
    for kinds, period in REFERENCE_PERIOD_COUNTS:
        if period == "release" and not rels:
            continue
        periods = documents.release_periods(day_rels) if period == "release" else period
        rows = retention.period_counts(subset(kinds), periods, r.return_gap_days)
        period_counts.append(
            {
                "kinds": kinds,
                "period": period,
                "rows": [
                    [
                        x.label,
                        x.active,
                        x.new,
                        x.returning,
                        x.continuing,
                        x.last_seen,
                        x.activity,
                        x.partial,
                    ]
                    for x in rows
                ],
            }
        )

    segments = []
    for kinds in REFERENCE_SEGMENTS:
        stats = retention.person_stats(subset(kinds), r)
        counts = {}
        for s in stats:
            people_n, current = counts.get(s.segment, (0, 0))
            counts[s.segment] = (people_n + 1, current + s.current)
        segments.append(
            {
                "kinds": kinds,
                "segments": {k: list(v) for k, v in sorted(counts.items())},
            }
        )

    all_stats = retention.person_stats(by_day, r)
    data_end = max((a.ts for a in by_day), default=0)
    cohorts = [
        [
            c.year,
            c.size,
            c.one_time,
            *(c.active_after[n] for n in retention.COHORT_OFFSETS),
        ]
        for c in retention.cohorts(all_stats, data_end)
    ]

    theme_trends = None
    if rels:
        day_docs = [dataclasses.replace(d, ts=_day_start(d.ts)) for d in docs]
        report = trends.analyze(
            day_docs,
            by_day,
            documents.release_periods(day_rels),
            trends.load_doc_themes(conn),
            trends.load_tagged(conn),
            trends.load_theme_names(conn),
            links,
            skip_in_progress=True,
        )
        theme_trends = {
            "periods": [
                {
                    "label": p.period.label,
                    "shares": {s.name: round(s.share, 6) for s in p.themes},
                }
                for p in report.periods
                if p.covered
            ],
            "labels": {t.name: t.label for t in report.trends},
        }

    return {
        "period_counts": period_counts,
        "segments": segments,
        "cohorts": cohorts,
        "theme_trends": theme_trends,
    }


def write(data: dict, path: str | Path) -> dict[str, int]:
    """Write compact JSON; returns the size in bytes of each top-level part."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    sizes = {
        k: len(json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode())
        for k, v in data.items()
    }
    sizes["total"] = len(text.encode())
    return sizes
