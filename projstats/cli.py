"""Command line entry point: python -m projstats <command> ..."""

import argparse
import subprocess
import sys
from datetime import UTC, datetime

from projstats import config, gitlog, identity, retention, storage


def cmd_fetch(args) -> int:
    cfg = config.load(args.config)
    action = gitlog.sync_clone(cfg.clone_url, cfg.clone_path)
    print(f"git: {action} {cfg.clone_path}")
    conn = storage.connect(cfg.db_path)
    s = gitlog.import_commits(conn, cfg.clone_path)
    notes = []
    if s.rewritten:
        notes.append("history was rewritten, so everything was reimported")
    if s.remapped:
        notes.append(".mailmap changed, so stored identities were re-mapped")
    print(f"commits: {s.new} new, {s.total} total (head {s.head[:7]})")
    for note in notes:
        print(f"  {note}")
    return 0


def cmd_people(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    identities = identity.load_identities(conn)
    result = identity.group_people(identities, cfg.people.bots)
    emails = len({i.email for i in identities})
    print(f"people: {len(result.people)} (from {emails} emails)")

    merged = [p for p in result.people if len(p.emails) > 1]
    print(f"\nmerged ({len(merged)}):")
    for p in merged:
        print(f"  {p.name}  [{', '.join(p.reasons)}]")
        for email in sorted(p.emails):
            print(f"      {email}")

    print(f"\nbots dropped ({len(result.bots)}):")
    for p in result.bots:
        print(f"  {p.name}  {', '.join(sorted(p.emails))}  ({p.activity})")
    return 0


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _pct(n: int | None, d: int) -> str:
    return "n/a" if n is None else f"{n} ({100 * n / d:.0f}%)"


def cmd_summary(args) -> int:
    """Temporary text report, to check the retention math until the page exists."""
    cfg = config.load(args.config)
    r = cfg.retention
    conn = storage.connect(cfg.db_path)
    people = identity.group_people(identity.load_identities(conn), cfg.people.bots)
    names = {p.key: p.name for p in people.people}
    activity = retention.load_commit_activity(conn, people)
    if not activity:
        print("error: no activity yet; run fetch first", file=sys.stderr)
        return 1
    stats = retention.person_stats(activity, r)
    data_end = max(a.ts for a in activity)
    total = len(activity)
    print(f"activity: {total} (commits, incl. co-authored)  people: {len(stats)}")
    print(f"range: {_day(activity[0].ts)} .. {_day(data_end)} (UTC)")

    print(
        f"\n== segments (core >= {r.core_quarters} quarters, regular >= "
        f"{r.regular_quarters}, casual < {r.regular_quarters} with >1, one-time = 1)"
    )
    print(f"  current = active in the last {r.return_gap_days} days of the data")
    for seg in ("core", "regular", "casual", "one-time"):
        members = [s for s in stats if s.segment == seg]
        n = sum(s.activity for s in members)
        current = sum(s.current for s in members)
        print(
            f"  {seg:9} {len(members):4} people {n:6} ({100 * n / total:4.1f}%)"
            f"  current {current:3}"
        )

    print("\n== cohorts by first-activity year (n/a = year not complete)")
    print(f"  {'year':4} {'size':>4} {'1-time':>6}  {'Y+1':>9} {'Y+2':>9} {'Y+5':>9}")
    for c in retention.cohorts(stats, data_end):
        after = [_pct(c.active_after[n], c.size) for n in retention.COHORT_OFFSETS]
        print(
            f"  {c.year:4} {c.size:4} {100 * c.one_time / c.size:5.0f}%  "
            + " ".join(f"{a:>9}" for a in after)
        )

    print(
        f"\n== per {args.period} (returning = back after >= {r.return_gap_days} days;"
        " last seen hidden while they may still return; * = partial)"
    )
    print(
        f"  {'period':8} {'active':>6} {'new':>4} {'ret':>4} {'cont':>4} "
        f"{'last':>4} {'activity':>8}"
    )
    for row in retention.period_counts(activity, args.period, r.return_gap_days):
        last = "-" if row.last_seen is None else row.last_seen
        mark = "*" if row.partial else ""
        print(
            f"  {row.label + mark:8} {row.active:6} {row.new:4} {row.returning:4} "
            f"{row.continuing:4} {last:>4} {row.activity:8}"
        )

    print("\n== top 15")
    print(
        f"  {'name':24} {'act':>5} {'first':10} {'last':10} {'yrs':>3} "
        f"{'qtrs':>4} {'gap_d':>5} {'ret':>3}  segment"
    )
    for s in stats[:15]:
        print(
            f"  {names[s.person][:24]:24} {s.activity:5} {_day(s.first)} "
            f"{_day(s.last)} {len(s.years):3} {s.quarters:4} "
            f"{s.longest_gap_days:5} {s.returns:3}  {s.segment}"
        )

    returners = sorted(
        (s for s in stats if s.returns), key=lambda s: -s.longest_gap_days
    )
    print(f"\n== returners ({len(returners)}), longest gap first")
    for s in returners[:15]:
        print(
            f"  {names[s.person][:24]:24} gap {s.longest_gap_days:5} days, "
            f"{s.returns} return(s), {s.activity} activity"
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="projstats", description="Contributor retention and topic trends"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="clone or update the repo and import new history")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("people", help="show how identities were grouped into people")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.set_defaults(func=cmd_people)

    p = sub.add_parser("summary", help="temporary text report of retention numbers")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.add_argument("--period", choices=list(retention.PERIOD_MONTHS), default="year")
    p.set_defaults(func=cmd_summary)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as e:
        cmd = " ".join(e.cmd[:4])
        print(
            f"error: `{cmd} ...` failed:\n{(e.stderr or '').strip()}", file=sys.stderr
        )
        return 1
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
