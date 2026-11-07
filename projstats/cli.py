"""Command line entry point: python -m projstats <command> ..."""

import argparse
import dataclasses
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from projstats import (
    config,
    documents,
    export,
    github,
    gitlog,
    identity,
    page,
    releases,
    retention,
    storage,
    tagger,
    themes,
)
from projstats.llm import CachedProvider, LLMError, OllamaProvider


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
    return identity.load_people(conn, cfg.people.bots)


def _load_activity(conn, cfg: config.Config, people, kinds=None):
    return retention.exclude_items(
        retention.load_activity(conn, people, kinds),
        cfg.activity.exclude_items,
        documents.commit_links(conn),
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


def _utc_date(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def cmd_themes(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    if args.action == "list":
        dates = {d.ref: d.ts for d in documents.load_documents(conn)}
        rows = themes.summary(conn, dates)
        if not rows:
            print("themes: none yet; run `projstats tag` first")
            return 0
        print(f"themes: {len(rows)}")
        print(f"  {'docs':>5}  {'first':10}  {'last':10}  name")
        for r in rows[: args.top]:
            first = _day(r.first) if r.first else "-"
            last = _day(r.last) if r.last else "-"
            also = f"  (also: {', '.join(r.aliases)})" if r.aliases else ""
            print(f"  {r.docs:5}  {first:10}  {last:10}  {r.name}{also}")
        return 0
    try:
        if args.action == "rename":
            themes.rename(conn, args.name, args.new_name)
            done = f"renamed '{args.name}' to '{args.new_name}'"
        elif args.action == "merge":
            themes.merge(conn, args.name, args.into)
            done = f"merged '{args.name}' into '{args.into}'"
        else:
            themes.delete(conn, args.name)
            done = f"deleted '{args.name}'; it won't be created again"
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(done)
    return 0


def _provider(cfg: config.Config) -> OllamaProvider:
    o = cfg.ollama
    # The token cap stops a looping model; a batch's reply is far shorter.
    return OllamaProvider(o.host, o.model, o.timeout, o.think, 4096, context=o.context)


def cmd_tag(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    docs = documents.load_documents(conn)
    if not docs:
        print("error: no documents yet; run fetch first", file=sys.stderr)
        return 1
    texts = documents.clean_documents(docs)
    settings = cfg.themes
    if args.batch_docs:
        settings = dataclasses.replace(settings, batch_docs=args.batch_docs)
    provider = _provider(cfg)
    try:
        if args.sample:
            return _sample_run(conn, provider, docs, texts, settings, args.sample)
        stats = tagger.tag_documents(
            conn,
            CachedProvider(provider, conn),
            docs,
            texts,
            settings,
            limit=args.limit,
            since=_utc_date(args.since) if args.since else None,
            force=args.force,
            progress=lambda line: print(line, flush=True),
            pause=args.pause,
        )
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        print("Progress so far is saved; rerun to continue.", file=sys.stderr)
        return 1
    print(
        f"documents: {stats.tagged} tagged, {stats.unchanged} unchanged, "
        f"{stats.failed} skipped (rerun to retry); {stats.themes_created} new "
        f"themes, {stats.aliases_added} aliases; {stats.seconds / 60:.1f} min"
    )
    return 0


def _sample_run(conn, provider, docs, texts, settings, n: int) -> int:
    """Tag a spread-out sample against an in-memory copy; nothing is saved."""
    periods = documents.release_periods(releases.load_releases(conn))
    picked = tagger.sample(docs, periods, n)
    text_of = {d.ref: t for d, t in zip(docs, texts, strict=True)}
    t = time.monotonic()
    provider.generate_json("warmup", "Reply in JSON.", "Say ok.", {"type": "object"})
    print(f"model {provider.model} loaded in {time.monotonic() - t:.1f}s")
    copy = tagger.memory_copy(conn)
    try:
        stats = tagger.tag_documents(
            copy,
            CachedProvider(provider, copy),
            picked,
            [text_of[d.ref] for d in picked],
            settings,
            force=True,
            progress=lambda line: print(line, flush=True),
        )
        rows = copy.execute(
            "SELECT d.doc_ref, t.name FROM doc_themes d JOIN themes t "
            "ON t.id = d.theme_id ORDER BY t.name"
        ).fetchall()
        found = copy.execute(
            "SELECT name, description FROM themes WHERE merged_into IS NULL "
            "ORDER BY name"
        ).fetchall()
    finally:
        copy.close()
    by_doc: dict[str, list[str]] = {}
    for ref, name in rows:
        by_doc.setdefault(ref, []).append(name)
    print(f"\n== {len(picked)} documents, {settings.batch_docs} per call (dry run)")
    for d in picked:
        tags = ", ".join(by_doc.get(d.ref, [])) or "-"
        print(f"  {_day(d.ts)} {d.ref:12} {d.title[:60]}\n      -> {tags}")
    print(f"\n== themes created ({len(found)})")
    for name, description in found:
        print(f"  {name}: {description}")
    per_doc = stats.seconds / max(1, stats.tagged)
    print(
        f"\n== time: {stats.seconds:.0f}s for {stats.tagged} documents "
        f"({per_doc:.2f}s each), {stats.failed} skipped; all {len(docs)} would "
        f"take about {per_doc * len(docs) / 3600:.1f}h"
    )
    return 0


def cmd_export(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    data = export.build(conn, cfg)
    out = args.out or Path(cfg.data_dir) / f"{cfg.slug}.json"
    sizes = export.write(data, out)
    a = data["activity"]
    missing = sum(1 for d in a["doc"] if d < 0)
    print(
        f"people {len(data['people']['name'])}, documents {len(data['docs']['ref'])}, "
        f"activity {len(a['day'])} ({missing} without a document), "
        f"themes {len(data['themes']['name'])}, tagged documents "
        f"{len(data['themes']['tagged'])}, releases {len(data['releases']['tag'])}"
    )
    for part, size in sizes.items():
        print(f"  {part:10} {size / 1024:8.1f} KB")
    print(f"-> {out}")
    return 0


def cmd_page(args) -> int:
    cfg = config.load(args.config)
    conn = storage.connect(cfg.db_path)
    data = export.build(conn, cfg)
    title = f"{cfg.repo.github.split('/')[-1]} contributors"
    out = page.write(data, title, args.out or Path(cfg.data_dir) / f"{cfg.slug}.html")
    size = out.stat().st_size / 1024
    print(
        f"page: {out} ({size:.0f} KB); add #check to the address to compare with Python"
    )
    if args.open:
        subprocess.run(["open", str(out)], check=False)
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

    p = sub.add_parser("themes", help="list, rename, merge, or delete themes")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.set_defaults(func=cmd_themes)
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("list", help="themes with document counts, most used first")
    a.add_argument("--top", type=int, default=100, help="rows to show (default 100)")
    a = actions.add_parser("rename", help="rename; the old name becomes an alias")
    a.add_argument("name")
    a.add_argument("new_name")
    a = actions.add_parser("merge", help="fold one theme into another")
    a.add_argument("name")
    a.add_argument("into")
    a = actions.add_parser("delete", help="remove a theme and block it")
    a.add_argument("name")

    p = sub.add_parser("tag", help="tag documents with themes using the local LLM")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.add_argument("--limit", type=int, help="tag at most N documents this run")
    p.add_argument("--since", help="only documents from YYYY-MM-DD (UTC) on")
    p.add_argument("--force", action="store_true", help="re-tag unchanged documents")
    p.add_argument(
        "--pause", type=float, default=0, help="seconds to rest between calls (cooler)"
    )
    p.add_argument(
        "--batch-docs", type=int, help="documents per model call (default: config)"
    )
    p.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="dry run: tag N documents spread across release cycles, save nothing",
    )
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("export", help="write the page's data as JSON")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.add_argument("--out", help="output file (default: data/<owner>__<repo>.json)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("page", help="write the web page (one self-contained HTML file)")
    p.add_argument("config", help="project config, e.g. projects/oiio.toml")
    p.add_argument("--out", help="output file (default: data/<owner>__<repo>.html)")
    p.add_argument("--open", action="store_true", help="open it in your browser")
    p.set_defaults(func=cmd_page)

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
