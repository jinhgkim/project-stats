"""Command line entry point: python -m projstats <command> ..."""

import argparse
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime

from projstats import (
    config,
    github,
    gitlog,
    identity,
    releases,
    retention,
    storage,
)


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
    found = releases.import_releases(conn, cfg.clone_path, cfg.releases.tag_pattern)
    if found:
        latest = found[-1]
        print(
            f"releases: {len(found)} (latest {latest.version}, "
            f"tagged {latest.tag} on {_day(latest.released_at)})"
        )
    else:
        print("releases: none match [releases] tag_pattern")
    if args.no_github:
        return 0

    owner, name = cfg.repo.github.split("/")
    fetcher = github.Fetcher(conn, github.GhClient(), owner, name)
    try:
        for kind in ("pr", "issue"):
            fetcher.fetch_items(kind, full=args.full)
        fetcher.fetch_commit_logins(full=args.full)
    finally:
        _print_github(conn, fetcher.stats, args.full)
    return 0


def _print_github(conn, stats: github.FetchStats, full: bool) -> None:
    for kind, label in (("pr", "PRs"), ("issue", "issues")):
        if kind not in stats.fetched:
            continue
        by_state = dict(
            conn.execute(
                "SELECT state, COUNT(*) FROM live_items WHERE kind = ? GROUP BY state",
                (kind,),
            ).fetchall()
        )
        states = ", ".join(f"{n} {s}" for s, n in sorted(by_state.items()))
        line = f"{label}: {stats.fetched[kind]} fetched; stored {states or 'none'}"
        if full:
            line += f"; {stats.vanished.get(kind, 0)} newly vanished"
        print(line)
    events = dict(
        conn.execute("SELECT kind, COUNT(*) FROM live_events GROUP BY kind").fetchall()
    )
    print(
        f"events: {stats.events} fetched; stored {events.get('review', 0)} reviews, "
        f"{events.get('comment', 0)} comments"
    )
    print(f"commit logins: {stats.commits} commits fetched")
    print(
        f"github api: {stats.queries} queries, cost {stats.cost}, "
        f"{stats.remaining} left (resets {stats.reset_at})"
    )


def _load_people(conn, cfg: config.Config) -> identity.People:
    return identity.group_people(
        identity.load_identities(conn),
        cfg.people.bots,
        links=identity.load_links(conn),
        github_logins=identity.load_github_logins(conn),
    )


def cmd_people(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    result = _load_people(conn, cfg)
    with_commits = [p for p in result.people if p.emails]
    linked = [p for p in with_commits if p.logins]
    print(
        f"people: {len(result.people)} ({len(with_commits)} with commits, "
        f"{len(linked)} of them linked to a GitHub login; "
        f"{len(result.people) - len(with_commits)} GitHub-only)"
    )

    merged = [p for p in result.people if p.reasons]
    print(f"\nmerged ({len(merged)}):")
    for p in merged:
        print(f"  {p.name}  [{', '.join(p.reasons)}]")
        for email in sorted(p.emails):
            print(f"      {email}")

    print(f"\nbots dropped ({len(result.bots)}):")
    for p in result.bots:
        ids = sorted(p.emails) or sorted(p.logins)
        print(f"  {p.name}  {', '.join(ids)}  ({p.activity})")
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
    people = _load_people(conn, cfg)
    names = {p.key: p.name for p in people.people}
    kinds = args.kinds.split(",") if args.kinds else list(retention.KINDS)
    activity = retention.load_activity(conn, people, kinds)
    if not activity:
        print("error: no activity yet; run fetch first", file=sys.stderr)
        return 1
    stats = retention.person_stats(activity, r)
    data_end = max(a.ts for a in activity)
    total = len(activity)
    per_kind = Counter(a.kind for a in activity)
    print(
        f"activity: {total} ("
        + ", ".join(f"{per_kind[k]} {k}" for k in retention.KINDS if k in kinds)
        + f")  people: {len(stats)}"
    )
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
    p.add_argument(
        "--full",
        action="store_true",
        help="refetch all GitHub data and flag what no longer exists",
    )
    p.add_argument("--no-github", action="store_true", help="git history only")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("people", help="show how identities were grouped into people")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.set_defaults(func=cmd_people)

    p = sub.add_parser("summary", help="temporary text report of retention numbers")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.add_argument("--period", choices=list(retention.PERIOD_MONTHS), default="year")
    p.add_argument(
        "--kinds",
        help="comma-separated activity kinds (default: all of "
        + ",".join(retention.KINDS)
        + ")",
    )
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
    except (OSError, ValueError, github.GitHubError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
