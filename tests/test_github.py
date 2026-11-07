import json
import subprocess
import unittest
from datetime import UTC, datetime

from projstats import storage
from projstats.github import (
    Fetcher,
    GhClient,
    GitHubError,
    TransientError,
)
from projstats.storage import get_state, set_state

NOW = int(datetime(2026, 2, 1, tzinfo=UTC).timestamp())


def iso(day: str) -> str:
    return f"2026-{day}Z" if "T" in day else f"2026-{day}T00:00:00Z"


def ts(day: str) -> int:
    return int(datetime.fromisoformat(iso(day).replace("Z", "+00:00")).timestamp())


def page(nodes, cursor=None):
    return {
        "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
        "nodes": nodes,
    }


def actor(login, bot=False):
    return {"login": login, "__typename": "Bot" if bot else "User"}


def comment(id, day="01-02", author=None):
    return {"id": id, "author": author, "createdAt": iso(day)}


def review(id, state="APPROVED", author=None):
    return {
        "id": id,
        "author": author,
        "state": state,
        "submittedAt": iso("01-03"),
        "createdAt": iso("01-03"),
    }


def item(id, number, updated, comments=(), reviews=None, more_comments=None, **kw):
    node = {
        "id": id,
        "number": number,
        "title": f"title {number}",
        "body": f"body {number}",
        "state": kw.get("state", "OPEN"),
        "createdAt": iso("01-01"),
        "updatedAt": iso(updated),
        "closedAt": None,
        "author": kw.get("author", actor("ann")),
        "labels": {"nodes": [{"name": n} for n in kw.get("labels", ())]},
        "comments": {
            "totalCount": len(comments),
            **page(list(comments), more_comments),
        },
    }
    if reviews is not None:
        node.update(
            mergedAt=kw.get("merged"),
            mergedBy=kw.get("merged_by"),
            mergeCommit={"oid": kw["sha"]} if "sha" in kw else None,
            reviews={"totalCount": len(reviews), **page(list(reviews))},
        )
    else:
        node["stateReason"] = kw.get("reason")
    return node


def commit(oid, *authors):
    return {
        "oid": oid,
        "authors": {
            "nodes": [
                {"email": e, "name": n, "user": {"login": u} if u else None}
                for e, n, u in authors
            ]
        },
    }


class FakeClient:
    """Serves canned pages keyed by (what, cursor); records every call."""

    def __init__(self, pages=None, remaining=4000, fail=None):
        self.pages = pages or {}
        self.remaining = remaining
        self.fail = fail  # callable(what, variables) -> bool: raise TransientError
        self.calls = []

    def query(self, query, variables):
        if "node(id:" in query:
            what = ("more", variables["id"])
        elif "pullRequests(" in query:
            what = "pr"
        elif "issues(" in query:
            what = "issue"
        else:
            what = "history"
        self.calls.append((what, variables.get("after"), variables["first"]))
        if self.fail and self.fail(what, variables):
            raise TransientError("HTTP 502")
        conn = self.pages[what, variables.get("after")]
        rate = {"cost": 1, "remaining": self.remaining, "resetAt": "soon"}
        if what == "pr":
            return {"rateLimit": rate, "repository": {"pullRequests": conn}}
        if what == "issue":
            return {"rateLimit": rate, "repository": {"issues": conn}}
        if what == "history":
            history = {"target": {"history": conn}}
            return {"rateLimit": rate, "repository": {"defaultBranchRef": history}}
        return {"rateLimit": rate, "node": {"comments": conn}}


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def fetcher(self, client):
        return Fetcher(self.conn, client, "o", "r", now=lambda: NOW)

    def rows(self, sql, *args):
        return [tuple(r) for r in self.conn.execute(sql, args)]

    def test_pages_and_saves_prs(self):
        pr1 = item(
            "P1",
            1,
            "01-20",
            comments=[comment("C1", author=None)],
            reviews=[review("R1", author=actor("copilot-pull-request-reviewer", True))],
            state="MERGED",
            labels=["bug", "python"],
            merged=iso("01-04"),
            merged_by=actor("lgritz"),
            sha="abc",
        )
        pr2 = item("P2", 2, "01-15", reviews=[], author=None)
        client = FakeClient({("pr", None): page([pr1], "x"), ("pr", "x"): page([pr2])})
        f = self.fetcher(client)
        f.fetch_items("pr")
        self.assertEqual(f.stats.fetched["pr"], 2)
        self.assertEqual(
            self.rows(
                "SELECT number, author_login, state, merged_by_login, merge_commit_sha,"
                " merged_at FROM items ORDER BY number"
            ),
            [
                (1, "ann", "merged", "lgritz", "abc", ts("01-04")),
                (2, None, "open", None, None, None),
            ],
        )
        self.assertEqual(
            self.rows("SELECT label FROM item_labels ORDER BY label"),
            [("bug",), ("python",)],
        )
        self.assertEqual(
            self.rows(
                "SELECT id, kind, author_login, review_state FROM events ORDER BY id"
            ),
            [
                ("C1", "comment", None, None),
                ("R1", "review", "copilot-pull-request-reviewer[bot]", "approved"),
            ],
        )
        self.assertEqual(get_state(self.conn, "github.pr.since"), str(NOW))

    def test_issues_keep_state_reason(self):
        issue = item("I1", 7, "01-20", state="CLOSED", reason="NOT_PLANNED")
        f = self.fetcher(FakeClient({("issue", None): page([issue])}))
        f.fetch_items("issue")
        self.assertEqual(
            self.rows("SELECT kind, state, state_reason FROM items"),
            [("issue", "closed", "not_planned")],
        )

    def test_rerun_stops_a_day_before_last_run(self):
        set_state(self.conn, "github.pr.since", str(ts("01-10")))
        nodes = [
            item("P3", 3, "01-20", reviews=[]),
            # Updated after the cutoff (a day before the last run), so kept.
            item("P2", 2, "01-09T12:00:00", reviews=[]),
            item("P1", 1, "01-08", reviews=[]),
        ]
        client = FakeClient({("pr", None): page(nodes, "next")})
        self.fetcher(client).fetch_items("pr")
        self.assertEqual(
            self.rows("SELECT number FROM items ORDER BY number"), [(2,), (3,)]
        )
        self.assertEqual([c[:2] for c in client.calls], [("pr", None)])  # no 2nd page

    def test_fetches_comments_past_the_first_page(self):
        pr = item(
            "P1",
            1,
            "01-20",
            comments=[comment("C1"), comment("C2")],
            reviews=[],
            more_comments="c2",
        )
        client = FakeClient(
            {
                ("pr", None): page([pr]),
                (("more", "P1"), "c2"): page([comment("C3")]),
            }
        )
        self.fetcher(client).fetch_items("pr")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM events"), [(3,)])

    def test_refetch_flags_missing_events_and_revives_them(self):
        def fetch(*comment_ids):
            pr = item(
                "P1", 1, "01-20", comments=[comment(c) for c in comment_ids], reviews=[]
            )
            self.fetcher(FakeClient({("pr", None): page([pr])})).fetch_items("pr", True)

        fetch("C1", "C2")
        fetch("C1")
        self.assertEqual(
            self.rows("SELECT id, vanished_at FROM events ORDER BY id"),
            [("C1", None), ("C2", NOW)],
        )
        self.assertEqual(self.rows("SELECT id FROM live_events"), [("C1",)])
        fetch("C1", "C2")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM live_events"), [(2,)])

    def test_full_flags_vanished_items_and_revives_them(self):
        a = item("A", 1, "01-20", comments=[comment("CA")], reviews=[])
        b = item("B", 2, "01-19", comments=[comment("CB")], reviews=[])
        self.fetcher(FakeClient({("pr", None): page([a, b])})).fetch_items("pr")

        f = self.fetcher(FakeClient({("pr", None): page([a])}))
        f.fetch_items("pr", full=True)
        self.assertEqual(f.stats.vanished["pr"], 1)
        self.assertEqual(self.rows("SELECT id FROM live_items"), [("A",)])
        self.assertEqual(self.rows("SELECT id FROM live_events"), [("CA",)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM items"), [(2,)])  # kept

        self.fetcher(FakeClient({("pr", None): page([a, b])})).fetch_items("pr", True)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM live_items"), [(2,)])

    def test_timeout_halves_page_size(self):
        client = FakeClient(
            {("pr", None): page([item("P1", 1, "01-20", reviews=[])])},
            fail=lambda what, v: v["first"] > 25,
        )
        self.fetcher(client).fetch_items("pr")
        self.assertEqual([c[2] for c in client.calls], [50, 25])

    def test_stops_before_budget_runs_out(self):
        client = FakeClient(
            {("pr", None): page([item("P1", 1, "01-20", reviews=[])])}, remaining=10
        )
        with self.assertRaisesRegex(GitHubError, "budget"):
            self.fetcher(client).fetch_items("pr")

    def test_history_stops_at_previous_head(self):
        c1 = commit("c1", ("Ann@A.example", "Ann", "ann"))
        c2 = commit(
            "c2",
            ("bo@b.example", "Bo", None),
            ("1+ann@users.noreply.github.com", "a", "ann"),
        )
        self.fetcher(
            FakeClient({("history", None): page([c2, c1])})
        ).fetch_commit_logins()
        self.assertEqual(get_state(self.conn, "github.history.head"), "c2")
        self.assertEqual(
            self.rows(
                "SELECT sha, email, login FROM commit_logins ORDER BY sha, email"
            ),
            [
                ("c1", "ann@a.example", "ann"),
                ("c2", "1+ann@users.noreply.github.com", "ann"),
                ("c2", "bo@b.example", None),
            ],
        )
        c3 = commit("c3", ("ann@a.example", "Ann", "ann"))
        client = FakeClient({("history", None): page([c3, c2], "more")})
        f = self.fetcher(client)
        f.fetch_commit_logins()
        self.assertEqual(f.stats.commits, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(get_state(self.conn, "github.history.head"), "c3")


class GhClientTest(unittest.TestCase):
    def run_with(self, *results):
        outputs = iter(results)

        def fake_run(cmd, **kw):
            code, out, err = next(outputs)
            return subprocess.CompletedProcess(cmd, code, out, err)

        sleeps = []
        client = GhClient(sleep=sleeps.append, run=fake_run)
        return client.query("query { x }", {}), sleeps

    def test_returns_data(self):
        data, _ = self.run_with((0, json.dumps({"data": {"x": 1}}), ""))
        self.assertEqual(data, {"x": 1})

    def test_retries_transient_failures(self):
        data, sleeps = self.run_with(
            (1, "", "gh: HTTP 502: Bad Gateway"),
            (0, json.dumps({"data": {"x": 2}}), ""),
        )
        self.assertEqual((data, sleeps), ({"x": 2}, [5]))

    def test_raises_on_query_errors(self):
        body = json.dumps({"errors": [{"message": "Field 'nope' doesn't exist"}]})
        with self.assertRaisesRegex(GitHubError, "nope"):
            self.run_with((1, body, "gh: GraphQL error"))

    def test_gives_up_after_retries(self):
        with self.assertRaises(TransientError):
            self.run_with(*[(1, "", "HTTP 504")] * 3)


class ReadOnlyTest(unittest.TestCase):
    def client(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, '{"data": {}}', "")

        return GhClient(run=fake_run), calls

    def test_mutations_never_reach_gh(self):
        client, calls = self.client()
        for query in (
            'mutation { addComment(input: {body: "x"}) { clientMutationId } }',
            "query { x }\nmutation { y }",
            "subscription { z }",
        ):
            with self.assertRaisesRegex(GitHubError, "only reads"):
                client.query(query, {})
        self.assertEqual(calls, [])

    def test_the_word_in_a_string_or_comment_is_fine(self):
        client, calls = self.client()
        client.query('query { search(query: "mutation fix") { x } } # no mutation', {})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
