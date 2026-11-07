"""Tag each document with the themes (efforts, functional areas) it belongs to.

Documents go to the model oldest first, a few per call, so themes named early
become the names later documents reuse. The loop structure (input hashes so
only new or changed documents rerun, failed batches retried next time) follows
~/projects/metacognition's extractor.py.
"""

import hashlib
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from projstats.config import ThemesConfig
from projstats.documents import Document, Period, assign
from projstats.llm import InvalidOutputError, Provider
from projstats.themes import Registry, resolve, theme_key

log = logging.getLogger(__name__)

VERSION = "tag-v2"  # bump when the prompt changes, so documents are re-tagged

GENERIC = {
    theme_key(name)
    for name in (
        "bug fix",
        "bug fixes",
        "bugfix",
        "bugfixes",
        "refactor",
        "refactoring",
        "cleanup",
        "code cleanup",
        "improvement",
        "improvements",
        "maintenance",
        "misc",
        "miscellaneous",
    )
}

SOURCES = {"pr": "PR", "issue": "Issue", "commit": "Commit"}

# Words that, next to the project's own name, still name the whole project:
# "OpenImageIO support", "OIIO core library".
FILLER = {
    "api",
    "apis",
    "base",
    "code",
    "codebase",
    "core",
    "development",
    "feature",
    "features",
    "functionality",
    "general",
    "internals",
    "library",
    "main",
    "project",
    "support",
    "the",
}

SYSTEM = """\
You label the work in an open-source software project. Each item is a pull \
request, an issue, or a commit. Label each item with the themes it belongs to.

About the project: {about}
{areas}
Rules:
- A theme is a lasting effort or functional area of the project, the kind of \
thing a release note or roadmap would name.
- Use the most specific area that fits: one file format, component, or tool, \
or an effort that spans several of them.
- Too narrow: a single function, class, or bug. Use the effort or area it \
belongs to instead.
- Too broad: the project as a whole ("{project} support", "{project} core"), \
or "Bug fix", "Refactoring", "Improvements", "Maintenance". Never use these.
- Tag a theme only when the item is mainly about it. A passing mention is not \
enough. When unsure, leave the theme out.
- Reuse an existing theme name exactly whenever it fits, including when the \
item uses a synonym or abbreviation for it. Give the name only, without its \
description.
- Otherwise name a new theme and list it in new_themes with a one-line \
description.
- Give each item 0 to {max_per_doc} themes. Trivial items (typo fixes, \
version bumps) get none.

The example below comes from a different project, an audio library. Its \
theme names are not themes of this project; never use them.

Example input:
[d1] PR, 2024-05-02
mp3: handle ID3v2 tags with unsynchronization
[d2] Issue, 2024-05-03
Crash when a plugin is unloaded during playback (it also happens with the \
new resampler)
[d3] Commit, 2024-05-04
Fix typo in README

Example output:
{{"documents": [
  {{"id": "d1", "themes": ["MP3 decoding"]}},
  {{"id": "d2", "themes": ["Plugin hosting"]}},
  {{"id": "d3", "themes": []}}],
 "new_themes": [
  {{"name": "MP3 decoding", "description": "Reading MP3 files and their tags"}},
  {{"name": "Plugin hosting", "description": "Loading and running plugins"}}]}}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "themes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "themes"],
            },
        },
        "new_themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["documents", "new_themes"],
}


@dataclass
class TagStats:
    tagged: int = 0  # documents tagged in this run
    unchanged: int = 0  # skipped: already tagged with the same input
    failed: int = 0  # in batches whose output was unusable; retried next run
    batches: int = 0
    themes_created: int = 0
    aliases_added: int = 0
    seconds: float = 0.0  # time spent tagging (model calls and saving)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " [...]"


def input_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{VERSION}\n{model}\n{text}".encode()).hexdigest()


def batches(
    items: list[tuple[Document, str]], max_docs: int, max_chars: int
) -> Iterator[list[tuple[Document, str]]]:
    """Consecutive groups of at most `max_docs` documents and `max_chars` text."""
    batch, size = [], 0
    for doc, text in items:
        if batch and (len(batch) == max_docs or size + len(text) > max_chars):
            yield batch
            batch, size = [], 0
        batch.append((doc, text))
        size += len(text)
    if batch:
        yield batch


def build_prompt(batch: list[tuple[Document, str]], themes: list[str]) -> tuple:
    """The user prompt, plus a map from local ids ("d1") to doc refs."""
    lines = ["Existing themes (reuse the exact names, without descriptions):"]
    lines += [f"- {t}" for t in themes] if themes else ["(none yet)"]
    lines += ["", "Items:"]
    local_ids = {}
    for doc, text in batch:
        local_id = f"d{len(local_ids) + 1}"
        local_ids[local_id] = doc.ref
        lines.append(f"[{local_id}] {SOURCES[doc.source]}, {_day(doc.ts)}")
        lines.append(text)
    return "\n".join(lines), local_ids


def is_catch_all(name: str, project_names: list[str]) -> bool:
    """True for a theme that names the whole project, like "OIIO core"."""
    key = theme_key(name)
    for project in project_names:
        pattern = rf"(?:^| ){re.escape(theme_key(project))}(?= |$)"
        if re.search(pattern, key):
            rest = re.sub(pattern, " ", key).split()
            if all(word in FILLER for word in rest):
                return True
    return False


def parse(
    result: dict, local_ids: dict, max_per_doc: int, project_names: list[str] = ()
) -> tuple[dict, dict]:
    """Validate model output: ({doc_ref: [names]}, {theme_key: description})."""
    tags: dict[str, list[str]] = {}
    for item in result.get("documents") or []:
        if not isinstance(item, dict):
            continue
        ref = local_ids.get(str(item.get("id", "")).strip("[] "))
        names = item.get("themes")
        if ref is None or not isinstance(names, list):
            continue
        kept, keys = [], set()
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            key = theme_key(name)
            if not key or key in GENERIC or key in keys:
                continue
            if is_catch_all(name, project_names):
                continue
            keys.add(key)
            kept.append(name.strip())
        tags[ref] = kept[:max_per_doc]
    descriptions = {}
    for item in result.get("new_themes") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            descriptions[theme_key(item["name"])] = str(item.get("description", ""))
    return tags, descriptions


def _save(
    conn: sqlite3.Connection,
    batch: list,
    tags: dict,
    theme_ids: dict,
    hashes: dict,
) -> None:
    refs = [doc.ref for doc, _ in batch]
    rows = {(ref, theme_ids[n]) for ref, names in tags.items() for n in names}
    now = time.time()
    with conn:
        conn.executemany(
            "DELETE FROM doc_themes WHERE doc_ref = ?", [(r,) for r in refs]
        )
        conn.executemany(
            "INSERT INTO doc_themes (doc_ref, theme_id) VALUES (?, ?)", sorted(rows)
        )
        conn.executemany(
            """
            INSERT INTO doc_tagging (doc_ref, input_hash, tagged_at) VALUES (?, ?, ?)
            ON CONFLICT (doc_ref) DO UPDATE SET
                input_hash = excluded.input_hash, tagged_at = excluded.tagged_at
            """,
            [(r, hashes[r], now) for r in refs],
        )


def tag_documents(
    conn: sqlite3.Connection,
    llm: Provider,
    docs: list[Document],
    texts: list[str],
    cfg: ThemesConfig,
    limit: int | None = None,
    since: int | None = None,
    force: bool = False,
    progress: Callable[[str], None] = lambda _: None,
    pause: float = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> TagStats:
    """Tag every document whose input changed since it was last tagged.

    `texts` are the cleaned texts of `docs` (same order). At most `limit`
    documents are tagged in this run, and with `since` (a timestamp) only
    documents from then on.
    """
    stats = TagStats()
    registry = Registry(conn)
    done = dict(conn.execute("SELECT doc_ref, input_hash FROM doc_tagging"))
    todo, hashes = [], {}
    for doc, text in sorted(zip(docs, texts, strict=True), key=lambda p: p[0].ts):
        if since is not None and doc.ts < since:
            continue
        text = _clip(text, cfg.doc_chars)
        h = input_hash(llm.name, text)
        if done.get(doc.ref) == h and not force:
            stats.unchanged += 1
            continue
        hashes[doc.ref] = h
        todo.append((doc, text))
    if limit is not None:
        todo = todo[:limit]

    started = clock()
    finished = 0
    for batch in batches(todo, cfg.batch_docs, cfg.batch_chars):
        refs = [doc.ref for doc, _ in batch]
        prompt, local_ids = build_prompt(
            batch, registry.prompt_lines(cfg.registry_limit, descriptions=True)
        )
        try:
            result = llm.generate_json("tag", _system(cfg), prompt, SCHEMA)
            tags, descriptions = parse(
                result, local_ids, cfg.max_per_doc, cfg.project_names
            )
            tags = {
                ref: [n for n in names if not registry.is_blocked(n)]
                for ref, names in tags.items()
            }
            names = {n for ns in tags.values() for n in ns}
            theme_ids = resolve(registry, llm, names, descriptions, cfg.registry_limit)
        except InvalidOutputError as e:
            log.warning("skipped %s..%s: %s", refs[0], refs[-1], e)
            stats.failed += len(batch)
            finished += len(batch)
            progress(f"{refs[0]}..{refs[-1]}: skipped ({e}); rerun to retry")
            continue
        _save(conn, batch, tags, theme_ids, hashes)
        stats.batches += 1
        stats.tagged += len(batch)
        finished += len(batch)
        elapsed = clock() - started
        eta = elapsed / finished * (len(todo) - finished)
        progress(
            f"[{finished}/{len(todo)}] {_day(batch[0][0].ts)} {refs[0]}..{refs[-1]}: "
            f"{sum(1 for r in refs if tags.get(r))} with themes, "
            f"{len(registry)} themes so far, ETA {_duration(eta)}"
        )
        if pause:
            sleep(pause)  # lets the machine cool down between model calls

    stats.seconds = clock() - started
    stats.themes_created = registry.created
    stats.aliases_added = registry.aliased
    return stats


def _system(cfg: ThemesConfig) -> str:
    about = cfg.about or "(no description given)"
    areas = f"Main areas: {cfg.areas}\n" if cfg.areas else ""
    project = cfg.project_names[0] if cfg.project_names else "Project"
    return SYSTEM.format(
        about=about, areas=areas, project=project, max_per_doc=cfg.max_per_doc
    )


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def sample(docs: list[Document], periods: list[Period], n: int) -> list[Document]:
    """About `n` documents spread evenly across the periods, oldest first."""
    groups: list[list[Document]] = [[] for _ in periods]
    for doc, i in zip(docs, assign(docs, periods), strict=True):
        groups[i].append(doc)
    groups = [sorted(g, key=lambda d: d.ts) for g in groups if g]
    picked: list[Document] = []
    per_group = [
        n // len(groups) + (1 if i < n % len(groups) else 0) for i in range(len(groups))
    ]
    for group, k in zip(groups, per_group, strict=True):
        k = min(k, len(group))
        step = len(group) / k if k else 0
        picked += [group[int(j * step)] for j in range(k)]
    return sorted(picked, key=lambda d: d.ts)


def memory_copy(conn: sqlite3.Connection) -> sqlite3.Connection:
    """An in-memory copy of the database, for dry runs that must not save."""
    copy = sqlite3.connect(":memory:")
    conn.backup(copy)
    copy.row_factory = sqlite3.Row
    copy.execute("PRAGMA foreign_keys = ON")
    return copy
