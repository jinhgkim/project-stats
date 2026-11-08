"""Group commit identities (name, email) into people.

Emails are joined into one person when they share a multi-word name or a
GitHub login. Single-word names ("Luc", "Brady") never join on their own: too
likely to be different people.
"""

import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

NOREPLY = re.compile(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$")

# AI coding tools that show up as commit co-authors in every project. Matched
# only against emails and logins, never names: "Claude" is also a human name,
# and the tools' display names vary ("Claude Sonnet 4.6", "Copilot App").
AI_TOOL_BOTS = frozenset(
    {
        "claude",
        "noreply@anthropic.com",
        "cursoragent",
        "cursoragent@cursor.com",
        "copilot",
        "noreply@openai.com",  # Codex's default Co-authored-by trailer
    }
)


@dataclass(frozen=True)
class Identity:
    name: str
    email: str
    count: int


@dataclass
class Person:
    key: str  # the email with the most activity
    name: str  # most common name
    emails: set[str] = field(default_factory=set)
    logins: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)  # why emails were joined
    activity: int = 0


@dataclass
class People:
    people: list[Person]
    bots: list[Person]
    by_email: dict[str, Person]
    by_login: dict[str, Person]


def load_identities(conn: sqlite3.Connection) -> list[Identity]:
    """Mailmapped identities of commit authors and co-authors, with counts."""
    counts: Counter = Counter()
    for sql in (
        "SELECT author_name, author_email, COUNT(*) FROM commits GROUP BY 1, 2",
        "SELECT name, email, COUNT(*) FROM commit_coauthors GROUP BY 1, 2",
    ):
        for name, email, n in conn.execute(sql):
            counts[name, email.lower()] += n
    return [Identity(n, e, c) for (n, e), c in sorted(counts.items())]


def load_links(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(mailmapped email, login) pairs from GitHub's view of commit authors.

    GitHub reports raw emails, so they go through the same .mailmap result the
    commits table already holds.
    """
    mapped = {}
    for sql in (
        "SELECT DISTINCT raw_email, author_email FROM commits",
        "SELECT DISTINCT raw_email, email FROM commit_coauthors",
    ):
        for raw, email in conn.execute(sql):
            mapped[raw.lower()] = email.lower()
    rows = conn.execute(
        "SELECT DISTINCT email, login FROM commit_logins WHERE login IS NOT NULL"
    )
    return sorted({(mapped.get(email, email), login) for email, login in rows})


def load_github_logins(conn: sqlite3.Connection) -> dict[str, int]:
    """Activity count per login: PRs and issues opened, reviews, comments."""
    rows = conn.execute(
        """
        SELECT author_login, COUNT(*) FROM (
            SELECT author_login FROM live_items
            UNION ALL
            SELECT author_login FROM live_events
        ) WHERE author_login IS NOT NULL GROUP BY 1
        """
    )
    return dict(rows.fetchall())


def name_key(name: str) -> str | None:
    """Comparison key for names: ignores case, spacing, and accents.

    None for single-word names, which are never used to join people.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    words = plain.casefold().split()
    return " ".join(words) if len(words) >= 2 else None


def noreply_login(email: str) -> str | None:
    m = NOREPLY.match(email)
    return m.group(1).casefold() if m else None


class _UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def _is_bot(person: Person, names: Iterable[str], bots: set[str]) -> bool:
    if any(login.endswith("[bot]") for login in person.logins):
        return True
    if (person.emails | person.logins) & AI_TOOL_BOTS:
        return True
    keys = {n.casefold() for n in names} | person.emails | person.logins
    return bool(keys & bots)


def group_people(
    identities: Iterable[Identity],
    bots: Iterable[str] = (),
    links: Iterable[tuple[str, str]] = (),
    github_logins: Mapping[str, int] | None = None,
) -> People:
    """Join identities into people.

    `links` are extra (email, login) pairs. `github_logins` maps logins seen on
    GitHub to their activity counts; logins that never join a commit identity
    become login-only people, keyed "login:<login>".
    """
    identities = list(identities)
    links = [(e.lower(), login.casefold()) for e, login in links]
    uf = _UnionFind()
    # Which emails touch each name or login node, to explain merges later.
    touching: dict[tuple, set[str]] = defaultdict(set)

    def connect(email: str, node: tuple) -> None:
        uf.union(("email", email), node)
        touching[node].add(email)

    for ident in identities:
        uf.find(("email", ident.email))
        if key := name_key(ident.name):
            connect(ident.email, ("name", key))
        if login := noreply_login(ident.email):
            connect(ident.email, ("login", login))
    for email, login in links:
        connect(email, ("login", login))

    github: Counter = Counter()
    display: dict[str, str] = {}  # casefolded login -> login as GitHub writes it
    for login, n in (github_logins or {}).items():
        github[login.casefold()] += n
        display.setdefault(login.casefold(), login)

    groups: dict = defaultdict(list)
    for ident in identities:
        groups[uf.find(("email", ident.email))].append(ident)
    github_roots: dict = defaultdict(set)
    for login in github:
        github_roots[uf.find(("login", login))].add(login)

    people, dropped = [], []
    bot_keys = {b.casefold() for b in bots}
    for root, members in groups.items():
        by_email: Counter = Counter()
        by_name: Counter = Counter()
        for m in members:
            by_email[m.email] += m.count
            by_name[m.name] += m.count
        emails = set(by_email)
        logins = {
            node[1] for node in touching if node[0] == "login" and uf.find(node) == root
        } | github_roots.get(root, set())
        reasons = sorted(
            f"{kind} '{value}'"
            for (kind, value), touched in touching.items()
            if len(touched & emails) >= 2
        )
        person = Person(
            key=min(by_email, key=lambda e: (-by_email[e], e)),
            name=min(by_name, key=lambda n: (-by_name[n], n)),
            emails=emails,
            logins=logins,
            reasons=reasons,
            activity=sum(by_email.values()) + sum(github[lg] for lg in logins),
        )
        if _is_bot(person, by_name, bot_keys):
            dropped.append(person)
        else:
            people.append(person)

    # Login-only people: GitHub activity but no commit identity. Several logins
    # land here together only if they share an email that has no commit.
    for root, logins in github_roots.items():
        if root in groups:
            continue
        main = min(logins, key=lambda lg: (-github[lg], lg))
        person = Person(
            key=f"login:{main}",
            name=display[main],
            logins=set(logins),
            reasons=[f"login '{lg}'" for lg in sorted(logins)]
            if len(logins) > 1
            else [],
            activity=sum(github[lg] for lg in logins),
        )
        names = [display[lg] for lg in logins]
        if _is_bot(person, names, bot_keys):
            dropped.append(person)
        else:
            people.append(person)

    people.sort(key=lambda p: (-p.activity, p.key))
    dropped.sort(key=lambda p: (-p.activity, p.key))
    return People(
        people=people,
        bots=dropped,
        by_email={e: p for p in people for e in p.emails},
        by_login={login: p for p in people for login in p.logins},
    )


def load_people(conn: sqlite3.Connection, bots: Iterable[str] = ()) -> People:
    """Everyone with commits or GitHub activity, grouped and without bots."""
    return group_people(
        load_identities(conn),
        bots,
        links=load_links(conn),
        github_logins=load_github_logins(conn),
    )
