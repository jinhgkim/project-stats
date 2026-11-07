"""Command line entry point: python -m projstats <command> ..."""

import argparse
import subprocess
import sys

from projstats import config, gitlog, identity, storage


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
