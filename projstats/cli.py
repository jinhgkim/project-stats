"""Command line entry point: python -m projstats <command> ..."""

import argparse
import subprocess
import sys

from projstats import config, gitlog, storage


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="projstats", description="Contributor retention and topic trends"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="clone or update the repo and import new history")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.set_defaults(func=cmd_fetch)

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
