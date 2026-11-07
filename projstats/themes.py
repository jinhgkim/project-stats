"""Theme registry: stable theme ids behind names and aliases, plus manual fixes.

Adapted from ~/projects/metacognition (normalizer.py and topics.py): topics
became themes, and the merge prompt is about project efforts.
"""

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass

from projstats.llm import Provider

MERGE_SYSTEM = """\
You deduplicate theme names for an open-source software project. A theme is \
a lasting effort or functional area of the project.

For each candidate, decide whether it names the same effort or area as an \
existing theme or another candidate: a synonym, abbreviation, spelling \
variant, or plural (e.g. "Span APIs" = "Span-based APIs", "OCIO" = \
"OpenColorIO").
Do not merge themes that are merely related ("OpenEXR support" and "Deep \
images" differ; "Python bindings" and "Python wheels" differ).
When two candidates are the same, point the less standard name at the more \
standard one.

Return every candidate. Set "same_as" to the matching name exactly as listed, \
or to "" if it is a distinct theme."""

MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate": {"type": "string"},
                    "same_as": {"type": "string"},
                },
                "required": ["candidate", "same_as"],
            },
        }
    },
    "required": ["matches"],
}


def theme_key(name: str) -> str:
    """Comparison key: case- and punctuation-insensitive, but keeps + and #."""
    return re.sub(r"[^0-9a-z+#]+", " ", name.casefold()).strip()


class Registry:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.by_key: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.aliases: dict[str, list[str]] = {}
        self.created = 0
        self.aliased = 0
        self.blocked = {
            r["key"] for r in conn.execute("SELECT key FROM blocked_themes")
        }
        for row in conn.execute(
            "SELECT id, name, aliases FROM themes WHERE merged_into IS NULL"
        ):
            if not self.is_blocked(row["name"]):
                self._index(row["id"], row["name"], json.loads(row["aliases"]))

    def _index(self, theme_id: str, name: str, aliases: list[str]) -> None:
        self.names[theme_id] = name
        self.aliases[theme_id] = aliases
        for n in (name, *aliases):
            self.by_key[theme_key(n)] = theme_id

    def __len__(self) -> int:
        return len(self.names)

    def lookup(self, name: str) -> str | None:
        return self.by_key.get(theme_key(name))

    def is_blocked(self, name: str) -> bool:
        """True for themes the user deleted; they must not come back."""
        return theme_key(name) in self.blocked

    def prompt_lines(self, limit: int) -> list[str]:
        """Theme names (with aliases), most used first."""
        rows = self.conn.execute(
            """
            SELECT t.id FROM themes t
            LEFT JOIN doc_themes d ON d.theme_id = t.id
            WHERE t.merged_into IS NULL
            GROUP BY t.id
            ORDER BY COUNT(d.doc_ref) DESC, t.name
            """
        )
        lines = []
        for row in rows:
            if row["id"] not in self.names:
                continue
            if len(lines) == limit:
                break
            name, aliases = self.names[row["id"]], self.aliases[row["id"]]
            lines.append(f"{name} (also: {', '.join(aliases)})" if aliases else name)
        return lines

    def create(self, name: str, description: str = "") -> str:
        theme_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO themes (id, name, description, created_at) "
                "VALUES (?, ?, ?, ?)",
                (theme_id, name, description, time.time()),
            )
        self._index(theme_id, name, [])
        self.created += 1
        return theme_id

    def add_alias(self, theme_id: str, alias: str) -> None:
        if self.by_key.get(theme_key(alias)) == theme_id:
            return
        aliases = [*self.aliases[theme_id], alias]
        with self.conn:
            self.conn.execute(
                "UPDATE themes SET aliases = ? WHERE id = ?",
                (json.dumps(aliases), theme_id),
            )
        self._index(theme_id, self.names[theme_id], aliases)
        self.aliased += 1


def _merge_check(
    llm: Provider, registry: Registry, candidates: list[str], limit: int
) -> dict[str, str]:
    existing = [line.split(" (also:")[0] for line in registry.prompt_lines(limit)]
    prompt = "\n".join(
        [
            "Existing themes:",
            *([f"- {n}" for n in existing] or ["(none)"]),
            "",
            "Candidates:",
            *[f"- {c}" for c in candidates],
        ]
    )
    result = llm.generate_json("merge", MERGE_SYSTEM, prompt, MERGE_SCHEMA)

    valid = {theme_key(n): n for n in (*existing, *candidates)}
    by_key = {theme_key(c): c for c in candidates}
    merges = {}
    for item in result.get("matches") or []:
        if not isinstance(item, dict):
            continue
        candidate = by_key.get(theme_key(str(item.get("candidate", ""))))
        target = valid.get(theme_key(str(item.get("same_as", ""))))
        if candidate and target and theme_key(target) != theme_key(candidate):
            merges[candidate] = target
    return merges


def resolve(
    registry: Registry,
    llm: Provider,
    names: set[str],
    descriptions: dict[str, str],
    registry_limit: int = 300,
) -> dict[str, str]:
    """Map each theme name to a theme id, creating themes or aliases as needed.

    `descriptions` is keyed by theme_key(name).
    """
    unknown = sorted(n for n in names if registry.lookup(n) is None)
    merges = {}
    if unknown and len(registry) + len(unknown) > 1:
        merges = _merge_check(llm, registry, unknown, registry_limit)
    candidates = set(unknown)

    def place(name: str, depth: int = 0) -> str:
        if (theme_id := registry.lookup(name)) is not None:
            return theme_id
        target = merges.get(name)
        if target and depth < 3:
            target_id = (
                place(target, depth + 1)
                if target in candidates
                else registry.lookup(target)
            )
            if target_id is not None:
                registry.add_alias(target_id, name)
                return target_id
        return registry.create(name, descriptions.get(theme_key(name), ""))

    return {name: place(name) for name in sorted(names)}


def _find(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    theme_id = Registry(conn).lookup(name)
    if theme_id is None:
        raise ValueError(f"no theme named '{name}'")
    return conn.execute("SELECT * FROM themes WHERE id = ?", (theme_id,)).fetchone()


def _merge_aliases(keep_name: str, *groups: list[str]) -> list[str]:
    seen = {theme_key(keep_name)}
    merged = []
    for name in (n for group in groups for n in group):
        if theme_key(name) not in seen:
            seen.add(theme_key(name))
            merged.append(name)
    return merged


def rename(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Rename a theme. The old name stays as an alias unless only case changed."""
    theme = _find(conn, old)
    registry = Registry(conn)
    if registry.is_blocked(new):
        raise ValueError(f"'{new}' belongs to a deleted theme and can't be reused")
    other = registry.lookup(new)
    if other is not None and other != theme["id"]:
        raise ValueError(f"'{new}' is already a theme; use merge instead")
    aliases = _merge_aliases(new, json.loads(theme["aliases"]), [theme["name"]])
    with conn:
        conn.execute(
            "UPDATE themes SET name = ?, aliases = ? WHERE id = ?",
            (new, json.dumps(aliases), theme["id"]),
        )


def merge(conn: sqlite3.Connection, source: str, target: str) -> None:
    """Fold `source` into `target`: its documents and names move to the target."""
    src, dst = _find(conn, source), _find(conn, target)
    if src["id"] == dst["id"]:
        raise ValueError(f"'{source}' and '{target}' are already the same theme")
    aliases = _merge_aliases(
        dst["name"],
        json.loads(dst["aliases"]),
        [src["name"]],
        json.loads(src["aliases"]),
    )
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO doc_themes (doc_ref, theme_id) "
            "SELECT doc_ref, ? FROM doc_themes WHERE theme_id = ?",
            (dst["id"], src["id"]),
        )
        conn.execute("DELETE FROM doc_themes WHERE theme_id = ?", (src["id"],))
        conn.execute(
            "UPDATE themes SET aliases = ? WHERE id = ?",
            (json.dumps(aliases), dst["id"]),
        )
        conn.execute(
            "UPDATE themes SET merged_into = ? WHERE id = ? OR merged_into = ?",
            (dst["id"], src["id"], src["id"]),
        )


def delete(conn: sqlite3.Connection, name: str) -> None:
    """Remove a theme's tags and stop it from being created again."""
    theme = _find(conn, name)
    keys = {theme_key(n) for n in [theme["name"], *json.loads(theme["aliases"])]}
    with conn:
        conn.execute("DELETE FROM doc_themes WHERE theme_id = ?", (theme["id"],))
        conn.executemany(
            "INSERT OR IGNORE INTO blocked_themes (key) VALUES (?)",
            [(k,) for k in sorted(keys)],
        )


def is_retired(conn: sqlite3.Connection, theme_id: str) -> bool:
    """True if a theme was merged away or deleted."""
    row = conn.execute(
        "SELECT name, merged_into FROM themes WHERE id = ?", (theme_id,)
    ).fetchone()
    if row is None or row["merged_into"] is not None:
        return True
    return Registry(conn).is_blocked(row["name"])


@dataclass
class ThemeRow:
    id: str
    name: str
    aliases: list[str]
    docs: int
    first: int | None  # earliest tagged document's date
    last: int | None


def summary(conn: sqlite3.Connection, doc_dates: dict[str, int]) -> list[ThemeRow]:
    """Live themes with document counts and date range, most used first.

    `doc_dates` maps doc_ref to the document's timestamp.
    """
    refs: dict[str, list[str]] = {}
    for theme_id, ref in conn.execute("SELECT theme_id, doc_ref FROM doc_themes"):
        refs.setdefault(theme_id, []).append(ref)
    registry = Registry(conn)
    rows = []
    for theme_id, name in registry.names.items():
        dates = [doc_dates[r] for r in refs.get(theme_id, []) if r in doc_dates]
        rows.append(
            ThemeRow(
                theme_id,
                name,
                registry.aliases[theme_id],
                len(refs.get(theme_id, [])),
                min(dates, default=None),
                max(dates, default=None),
            )
        )
    rows.sort(key=lambda r: (-r.docs, r.name))
    return rows
