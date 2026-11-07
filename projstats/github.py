"""Fetch PRs, issues, reviews, comments, and commit logins from GitHub.

Talks to GitHub's GraphQL API through `gh api graphql`, so authentication is
whatever `gh auth login` set up. Every page is saved as it arrives; a run that
stops halfway can simply be rerun.
"""

import json
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

from projstats.storage import get_state, set_state

DAY = 86_400
MIN_PAGE = 5
RATE_FLOOR = 50  # stop before the hourly budget runs out completely

RATE = "rateLimit { cost remaining resetAt }"
ACTOR = "{ login __typename }"
EVENTS_PAGE = "pageInfo { hasNextPage endCursor }"
REVIEW_FIELDS = f"id author {ACTOR} state submittedAt createdAt"
COMMENT_FIELDS = f"id author {ACTOR} createdAt"

ITEM_FIELDS = f"""
    id number title body state createdAt updatedAt closedAt author {ACTOR}
    labels(first: 50) {{ nodes {{ name }} }}
    comments(first: 100) {{ totalCount {EVENTS_PAGE} nodes {{ {COMMENT_FIELDS} }} }}
"""
PR_FIELDS = f"""
    {ITEM_FIELDS}
    mergedAt mergedBy {ACTOR} mergeCommit {{ oid }}
    reviews(first: 100) {{ totalCount {EVENTS_PAGE} nodes {{ {REVIEW_FIELDS} }} }}
"""
ISSUE_FIELDS = f"{ITEM_FIELDS} stateReason"

LIST_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String) {
  %(rate)s
  repository(owner: $owner, name: $name) {
    %(conn)s(first: $first, after: $after,
             orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { %(fields)s }
    }
  }
}
"""
MORE_QUERY = """
query($id: ID!, $first: Int!, $after: String) {
  %(rate)s
  node(id: $id) {
    ... on %(type)s {
      %(conn)s(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { %(fields)s }
      }
    }
  }
}
"""
HISTORY_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String) {
  %(rate)s
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { oid authors(first: 20) { nodes { email name user { login } } } }
      }
    } } }
  }
}
"""

KINDS = {
    # kind: (connection, GraphQL type, fields, page size)
    "pr": ("pullRequests", "PullRequest", PR_FIELDS, 50),
    "issue": ("issues", "Issue", ISSUE_FIELDS, 100),
}


class GitHubError(RuntimeError):
    pass


class TransientError(GitHubError):
    """A failure worth retrying with a smaller page (timeouts, 5xx)."""


TRANSIENT_MARKERS = (
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "timeout",
    "timed out",
    "Something went wrong",
    "secondary rate limit",
)


class GhClient:
    def __init__(self, retries: int = 3, sleep: Callable[[float], None] = time.sleep):
        self.retries = retries
        self.sleep = sleep

    def query(self, query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables})
        message = ""
        for attempt in range(self.retries):
            r = subprocess.run(
                ["gh", "api", "graphql", "--input", "-"],
                input=body,
                capture_output=True,
                text=True,
            )
            try:
                payload = json.loads(r.stdout) if r.stdout.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            if r.returncode == 0 and not payload.get("errors"):
                return payload["data"]
            errors = payload.get("errors") or []
            message = (
                "; ".join(e.get("message", "") for e in errors) or r.stderr.strip()
            )
            if not any(m.lower() in message.lower() for m in TRANSIENT_MARKERS):
                raise GitHubError(message)
            self.sleep(5 * 2**attempt)
        raise TransientError(message)


@dataclass
class FetchStats:
    fetched: dict[str, int] = field(default_factory=dict)  # kind -> items saved
    vanished: dict[str, int] = field(default_factory=dict)
    events: int = 0
    commits: int = 0
    queries: int = 0
    cost: int = 0
    remaining: int | None = None
    reset_at: str = ""


def _ts(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _login(actor: dict | None) -> str | None:
    """Bots get a "[bot]" suffix, as in GitHub's REST API and noreply emails."""
    if not actor:
        return None
    login = actor["login"]
    if actor.get("__typename") == "Bot" and not login.endswith("[bot]"):
        login += "[bot]"
    return login


class Fetcher:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client,
        owner: str,
        name: str,
        now: Callable[[], int] = lambda: int(time.time()),
    ):
        self.conn = conn
        self.client = client
        self.repo = {"owner": owner, "name": name}
        self.now = now
        self.stats = FetchStats()

    def _query(self, query: str, variables: dict) -> dict:
        data = self.client.query(query, variables)
        rate = data.get("rateLimit") or {}
        self.stats.queries += 1
        self.stats.cost += rate.get("cost", 0)
        self.stats.remaining = rate.get("remaining", self.stats.remaining)
        self.stats.reset_at = rate.get("resetAt", self.stats.reset_at)
        if self.stats.remaining is not None and self.stats.remaining < RATE_FLOOR:
            raise GitHubError(
                f"GitHub API budget nearly used up ({self.stats.remaining} left); "
                f"it resets at {self.stats.reset_at}. Rerun then; progress is saved."
            )
        return data

    def _pages(
        self,
        query: str,
        variables: dict,
        path: Callable[[dict], dict],
        first: int,
        after: str | None = None,
    ) -> Iterator[list[dict]]:
        """Yield each page's nodes, halving the page size on timeouts."""
        while True:
            try:
                data = self._query(query, {**variables, "first": first, "after": after})
            except TransientError:
                if first <= MIN_PAGE:
                    raise
                first = max(MIN_PAGE, first // 2)
                continue
            conn = path(data)
            yield conn["nodes"]
            if not conn["pageInfo"]["hasNextPage"]:
                return
            after = conn["pageInfo"]["endCursor"]

    def _all_events(self, node: dict, kind: str, conn_name: str, fields: str) -> list:
        """The connection's nodes, fetching past the first 100 if needed."""
        conn = node[conn_name]
        nodes = list(conn["nodes"])
        if conn["pageInfo"]["hasNextPage"]:
            query = MORE_QUERY % {
                "rate": RATE,
                "type": KINDS[kind][1],
                "conn": conn_name,
                "fields": fields,
            }
            for page in self._pages(
                query,
                {"id": node["id"]},
                lambda d: d["node"][conn_name],
                100,
                conn["pageInfo"]["endCursor"],
            ):
                nodes.extend(page)
        return nodes

    def _save_item(self, kind: str, node: dict) -> None:
        comments = self._all_events(node, kind, "comments", COMMENT_FIELDS)
        reviews = (
            self._all_events(node, kind, "reviews", REVIEW_FIELDS)
            if kind == "pr"
            else []
        )
        item_id = node["id"]
        self.conn.execute(
            """
            INSERT INTO items (id, number, kind, author_login, title, body, state,
                state_reason, created_at, updated_at, closed_at, merged_at,
                merged_by_login, merge_commit_sha, vanished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT (id) DO UPDATE SET
                number = excluded.number, author_login = excluded.author_login,
                title = excluded.title, body = excluded.body, state = excluded.state,
                state_reason = excluded.state_reason, updated_at = excluded.updated_at,
                closed_at = excluded.closed_at, merged_at = excluded.merged_at,
                merged_by_login = excluded.merged_by_login,
                merge_commit_sha = excluded.merge_commit_sha, vanished_at = NULL
            """,
            (
                item_id,
                node["number"],
                kind,
                _login(node.get("author")),
                node["title"],
                node.get("body") or "",
                node["state"].lower(),
                (node.get("stateReason") or "").lower() or None,
                _ts(node["createdAt"]),
                _ts(node["updatedAt"]),
                _ts(node.get("closedAt")),
                _ts(node.get("mergedAt")),
                _login(node.get("mergedBy")),
                (node.get("mergeCommit") or {}).get("oid"),
            ),
        )
        self.conn.execute("DELETE FROM item_labels WHERE item_id = ?", (item_id,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO item_labels (item_id, label) VALUES (?, ?)",
            [(item_id, label["name"]) for label in node["labels"]["nodes"]],
        )
        events = [
            (
                e["id"],
                item_id,
                "comment",
                _login(e.get("author")),
                _ts(e["createdAt"]),
                None,
            )
            for e in comments
        ] + [
            (
                e["id"],
                item_id,
                "review",
                _login(e.get("author")),
                _ts(e.get("submittedAt") or e["createdAt"]),
                e["state"].lower(),
            )
            for e in reviews
        ]
        self.conn.executemany(
            """
            INSERT INTO events (id, item_id, kind, author_login, created_at,
                                review_state, vanished_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT (id) DO UPDATE SET
                author_login = excluded.author_login, created_at = excluded.created_at,
                review_state = excluded.review_state, vanished_at = NULL
            """,
            events,
        )
        # This fetch saw every event on the item, so missing ones are gone.
        ids = [e[0] for e in events]
        self.conn.execute(
            "UPDATE events SET vanished_at = ? WHERE item_id = ?"
            " AND vanished_at IS NULL"
            f" AND id NOT IN ({','.join('?' * len(ids))})",
            (self.now(), item_id, *ids),
        )
        self.stats.events += len(events)

    def fetch_items(self, kind: str, full: bool = False) -> None:
        """PRs or issues updated since the last run (all of them if `full`)."""
        conn_name, _, fields, page_size = KINDS[kind]
        state_key = f"github.{kind}.since"
        started = self.now()
        since = None if full else get_state(self.conn, state_key)
        cutoff = int(since) - DAY if since else None
        query = LIST_QUERY % {"rate": RATE, "conn": conn_name, "fields": fields}
        seen: set[str] = set()
        for nodes in self._pages(
            query, self.repo, lambda d: d["repository"][conn_name], page_size
        ):
            done = False
            with self.conn:
                for node in nodes:
                    if cutoff is not None and _ts(node["updatedAt"]) < cutoff:
                        done = True
                        break
                    self._save_item(kind, node)
                    seen.add(node["id"])
            if done:
                break
        self.stats.fetched[kind] = len(seen)
        with self.conn:
            if full:
                cur = self.conn.execute(
                    f"UPDATE items SET vanished_at = ? WHERE kind = ? AND vanished_at"
                    f" IS NULL AND id NOT IN ({','.join('?' * len(seen))})",
                    (started, kind, *seen),
                )
                self.stats.vanished[kind] = cur.rowcount
            set_state(self.conn, state_key, str(started))

    def fetch_commit_logins(self, full: bool = False) -> None:
        """Logins of main-branch commit authors, newest first, down to the last run.

        Stopping at the previous head assumes history is mostly linear (true for
        squash/rebase merges); `full` refetches everything.
        """
        stop_at = None if full else get_state(self.conn, "github.history.head")
        head = None
        seen: set[str] = set()

        def path(data: dict) -> dict:
            return data["repository"]["defaultBranchRef"]["target"]["history"]

        query = HISTORY_QUERY % {"rate": RATE}
        for nodes in self._pages(query, self.repo, path, 100):
            done = False
            with self.conn:
                for node in nodes:
                    head = head or node["oid"]
                    if node["oid"] == stop_at:
                        done = True
                        break
                    self.conn.execute(
                        "DELETE FROM commit_logins WHERE sha = ?", (node["oid"],)
                    )
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO commit_logins (sha, email, name, login)"
                        " VALUES (?, ?, ?, ?)",
                        [
                            (
                                node["oid"],
                                a["email"].lower(),
                                a["name"],
                                (a.get("user") or {}).get("login"),
                            )
                            for a in node["authors"]["nodes"]
                            if a.get("email")
                        ],
                    )
                    seen.add(node["oid"])
            if done:
                break
        self.stats.commits = len(seen)
        with self.conn:
            if full:
                # Commits are git's data, not GitHub's: stale rows just go.
                self.conn.execute(
                    f"DELETE FROM commit_logins WHERE sha NOT IN"
                    f" ({','.join('?' * len(seen))})",
                    tuple(seen),
                )
            if head:
                set_state(self.conn, "github.history.head", head)
