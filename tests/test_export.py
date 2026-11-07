import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from projstats import export, storage, themes
from projstats.config import ActivityConfig, Config, PeopleConfig, RepoConfig
from tests.github_rows import add_commit, add_commit_login, add_event, add_item


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


class ExportTest(unittest.TestCase):
    def setUp(self):
        conn = self.conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        commits = [
            ("c1", "2020-01-01T10:00", "init"),
            ("c2", "2020-02-01T10:00", "squashed work (#5)"),
            ("c4", "2020-12-31T23:30", "Fix it. Patch by: Zed <zed@z.example>"),
        ]
        for sha, when, subject in commits:
            add_commit(conn, sha, ts(when), "Ann Lee", "ann@a.example")
            conn.execute("UPDATE commits SET subject = ? WHERE sha = ?", (subject, sha))
        add_commit_login(conn, "c1", "ann@a.example", "ann")
        add_item(conn, "P5", 5, "pr", "ann", ts("2020-01-15T00:00"))
        add_item(conn, "I6", 6, "issue", "bo", ts("2020-03-01T00:00"))
        add_item(conn, "P7", 7, "pr", "bo", ts("2020-04-01T00:00"), vanished=1)
        conn.execute(
            "UPDATE items SET title = 'pin openimageio@2.3.1.0' WHERE id = 'I6'"
        )
        add_event(conn, "R1", "P5", "review", "bo", ts("2020-01-16T00:00"))
        add_event(
            conn, "C1", "I6", "comment", "dependabot[bot]", ts("2020-03-02T00:00")
        )
        alpha = themes.Registry(conn).create("Alpha")
        with conn:
            conn.execute("INSERT INTO doc_themes VALUES ('pr#5', ?)", (alpha,))
            conn.executemany(
                "INSERT INTO doc_tagging VALUES (?, 'h', 0)", [("pr#5",), ("issue#6",)]
            )
            conn.execute(
                "INSERT INTO releases VALUES ('1.0', 'v1.0.0', ?)",
                (ts("2020-06-01T15:00"),),
            )
        self.cfg = Config(repo=RepoConfig(github="o/r"), people=PeopleConfig())
        self.data = export.build(conn, self.cfg, generated="2026-11-06")

    def test_columns_line_up_and_indexes_are_valid(self):
        d = self.data
        for part in ("people", "docs", "activity", "releases"):
            lengths = {len(v) for v in d[part].values()}
            self.assertEqual(len(lengths), 1, part)
        a = d["activity"]
        self.assertTrue(all(0 <= p < len(d["people"]["name"]) for p in a["person"]))
        self.assertTrue(all(0 <= k < len(d["kinds"]) for k in a["kind"]))
        self.assertTrue(all(0 <= x < len(d["docs"]["ref"]) for x in a["doc"]))
        self.assertEqual(len(d["themes"]["doc"]), len(d["themes"]["theme"]))

    def test_people_without_bots_or_emails(self):
        p = self.data["people"]
        self.assertEqual(
            sorted(zip(p["name"], p["login"], strict=True)),
            [("Ann Lee", "ann"), ("bo", "bo")],
        )

    def test_documents_skip_vanished_and_linked_commits(self):
        docs = self.data["docs"]
        refs = list(zip(docs["source"], docs["ref"], strict=True))
        self.assertEqual(
            refs, [("commit", "c1"), ("pr", "5"), ("issue", "6"), ("commit", "c4")]
        )

    def test_linked_commit_activity_points_at_its_pr(self):
        d = self.data
        a = d["activity"]
        pr5 = d["docs"]["ref"].index("5")
        commit = d["kinds"].index("commit")
        commit_docs = [
            a["doc"][i] for i in range(len(a["day"])) if a["kind"][i] == commit
        ]
        self.assertEqual(commit_docs.count(pr5), 1)  # c2 "(#5)"

    def test_days_are_utc(self):
        a = self.data["activity"]
        last_commit_day = max(a["day"])
        self.assertEqual(last_commit_day, ts("2020-12-31T00:00") // 86_400)
        self.assertEqual(
            self.data["releases"]["day"], [ts("2020-06-01T00:00") // 86_400]
        )

    def test_emails_are_redacted_but_version_pins_kept(self):
        text = json.dumps(self.data)
        self.assertNotIn("ann@a.example", text)
        self.assertNotIn("zed@z.example", text)
        titles = self.data["docs"]["title"]
        self.assertIn("Fix it. Patch by: Zed <[email]>", titles)
        self.assertIn("pin openimageio@2.3.1.0", titles)

    def test_themes_and_coverage(self):
        t = self.data["themes"]
        self.assertEqual(t["name"], ["Alpha"])
        docs = self.data["docs"]["ref"]
        self.assertEqual([docs[i] for i in t["doc"]], ["5"])
        self.assertEqual(sorted(docs[i] for i in t["tagged"]), ["5", "6"])

    def test_sources_are_first_days_per_kind(self):
        self.assertEqual(
            self.data["sources"],
            {
                "commit": ts("2020-01-01T00:00") // 86_400,
                "issue": ts("2020-03-01T00:00") // 86_400,
                "pr": ts("2020-01-15T00:00") // 86_400,
                "review": ts("2020-01-16T00:00") // 86_400,
            },
        )

    def test_reference_numbers(self):
        ref = self.data["reference"]
        self.assertEqual(
            [(r["kinds"], r["period"]) for r in ref["period_counts"]],
            [
                (None, "year"),
                (["commit"], "quarter"),
                (["review"], "month"),
                (["commit", "pr", "issue"], "release"),
            ],
        )
        # One year, 2020: Ann (3 commits, 1 PR) and bo (1 review, 1 issue) are new.
        self.assertEqual(
            ref["period_counts"][0]["rows"], [["2020", 2, 2, 0, 0, None, 6, True]]
        )
        # Release 1.0 on 2020-06-01 splits off c4 (2020-12-31), Ann's next commit.
        self.assertEqual(
            ref["period_counts"][3]["rows"],
            [
                ["1.0 cycle", 2, 2, 0, 0, None, 4, False],
                ["after 1.0", 1, 0, 0, 1, None, 1, True],
            ],
        )
        # Ann has 4 of 6 activities and bo 2: 80% needs both, so both are core.
        self.assertEqual(ref["segments"][0]["segments"], {"core": [2, 2]})
        self.assertEqual(ref["cohorts"], [[2020, 2, 0, None, None, None]])
        # The release splits 2020: pr#5 and issue#6 fall in the 1.0 cycle.
        self.assertEqual(
            [p["label"] for p in ref["theme_trends"]["periods"]], ["1.0 cycle"]
        )

    def test_excluded_items_leave_activity_out(self):
        self.assertEqual(self.data["project"]["excluded_items"], [])
        self.cfg.activity = ActivityConfig(exclude_items=[5])
        data = export.build(self.conn, self.cfg, generated="2026-11-06")
        a = data["activity"]
        kinds = [data["kinds"][k] for k in a["kind"]]
        # c2 "(#5)", the PR itself, and its review are gone.
        self.assertEqual(kinds, ["commit", "issue", "commit"])
        self.assertEqual(data["project"]["excluded_items"], [5])
        self.assertEqual(data["reference"]["period_counts"][0]["rows"][0][6], 3)

    def test_write_reports_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            sizes = export.write(self.data, path)
            self.assertEqual(sizes["total"], path.stat().st_size)
            self.assertEqual(json.loads(path.read_text()), self.data)


class RedactTest(unittest.TestCase):
    def test_redact(self):
        self.assertEqual(export.redact("mail a.b+c@x-y.co.uk now"), "mail [email] now")
        self.assertEqual(export.redact("openjpeg@2.3"), "openjpeg@2.3")


if __name__ == "__main__":
    unittest.main()
