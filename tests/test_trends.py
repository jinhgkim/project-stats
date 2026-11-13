"""Theme trends on a hand-counted fixture.

Releases 1.0 (2020), 1.1 (2021), 1.2 (2022) give four periods:
  P0 "1.0 cycle"  (before 2020)  commit c0, untagged             -> not covered
  P1 "1.1 cycle"  (2020)         pr#1 {A}, pr#2 {B}, issue#3 {} (tagged, no theme)
  P2 "1.2 cycle"  (2021)         pr#4 {A}, pr#5 {A}, issue#6 {B}, commit bbbb {A}
  P3 "after 1.2"  (2022-)        pr#7 {C}, in progress
Activity:
  P1: commit aaaa (linked to pr#1, ann), review on pr#1 (bo), pr#2 opened (bo),
      issue#3 opened (cy)                         -> 4 on tagged docs
      A: code 1 + discussion 1 = 2/4 = 0.50;  B: code 1 = 1/4 = 0.25
  P2: pr#4 opened (ann), commit bbbb (ann), comment on pr#5 (bo),
      issue#6 opened (cy)                         -> 4 on tagged docs
      A: code 2 + discussion 1 = 3/4 = 0.75;  B: discussion 1 = 1/4 = 0.25
  P3: pr#7 opened (ann) -> C 1/1
  P0: commit c0 (ann) is on an untagged doc and ignored.
Trends compare P2 with P1 (P3 is in progress): A 0.75 vs 0.50 = 1.5x -> rising;
B 0.25 vs 0.25 -> steady; C has no docs in P1/P2 -> too few.
"""

import unittest
from datetime import UTC, datetime

from projstats import storage, themes
from projstats.documents import Document, commit_links, release_periods
from projstats.releases import Release
from projstats.retention import Activity
from projstats.trends import (
    analyze,
    doc_ref_of,
    load_doc_themes,
    load_tagged,
    load_theme_names,
)
from tests.github_rows import add_commit, add_item


def ts(year, month=6):
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp())


PERIODS = release_periods(
    [
        Release("1.0", "a", ts(2020, 1)),
        Release("1.1", "b", ts(2021, 1)),
        Release("1.2", "c", ts(2022, 1)),
    ]
)
DOCS = [
    Document("commit", "c000000000", ts(2019), "old", ""),
    Document("pr", "pr#1", ts(2020, 3), "", ""),
    Document("pr", "pr#2", ts(2020, 6), "", ""),
    Document("issue", "issue#3", ts(2020, 9), "", ""),
    Document("pr", "pr#4", ts(2021, 3), "", ""),
    Document("pr", "pr#5", ts(2021, 4), "", ""),
    Document("issue", "issue#6", ts(2021, 5), "", ""),
    Document("commit", "bbbbbbbbbb", ts(2021, 6), "", ""),
    Document("pr", "pr#7", ts(2022, 2), "", ""),
]
DOC_THEMES = {
    "pr#1": {"A"},
    "pr#2": {"B"},
    "pr#4": {"A"},
    "pr#5": {"A"},
    "issue#6": {"B"},
    "bbbbbbbbbb": {"A"},
    "pr#7": {"C"},
}
TAGGED = {d.ref for d in DOCS} - {"c000000000"}
NAMES = {"A": "Alpha", "B": "Beta", "C": "Gamma"}
LINKS = {"aaaaaaaaaaaaaaaa": "pr#1"}
ACTIVITY = [
    Activity("ann", ts(2019), "commit", "c000000000ffff"),
    Activity("ann", ts(2020, 3), "commit", "aaaaaaaaaaaaaaaa"),
    Activity("bo", ts(2020, 3), "review", "pr#1"),
    Activity("bo", ts(2020, 6), "pr", "pr#2"),
    Activity("cy", ts(2020, 9), "issue", "issue#3"),
    Activity("ann", ts(2021, 3), "pr", "pr#4"),
    Activity("ann", ts(2021, 6), "commit", "bbbbbbbbbbffff"),
    Activity("bo", ts(2021, 4), "comment", "pr#5"),
    Activity("cy", ts(2021, 5), "issue", "issue#6"),
    Activity("ann", ts(2022, 2), "pr", "pr#7"),
]
PEOPLE = {"ann": "Ann", "bo": "Bo", "cy": "Cy"}


def report(**kw):
    args = dict(person_names=PEOPLE, skip_in_progress=True, min_docs=2)
    args.update(kw)
    return analyze(DOCS, ACTIVITY, PERIODS, DOC_THEMES, TAGGED, NAMES, LINKS, **args)


def stats(period):
    return {
        s.name: (s.docs, s.code, s.discussion, s.people, s.share) for s in period.themes
    }


class DocRefTest(unittest.TestCase):
    def test_activity_to_document(self):
        self.assertEqual(doc_ref_of(ACTIVITY[1], LINKS), "pr#1")  # linked commit
        self.assertEqual(doc_ref_of(ACTIVITY[6], LINKS), "bbbbbbbbbb")  # own doc
        self.assertEqual(doc_ref_of(ACTIVITY[2], LINKS), "pr#1")  # review


class AnalyzeTest(unittest.TestCase):
    def test_periods_counts_and_shares(self):
        r = report()
        p0, p1, p2, p3 = r.periods
        self.assertEqual((p0.docs, p0.tagged, p0.covered, p0.themes), (1, 0, False, []))
        self.assertEqual((p1.docs, p1.tagged, p1.activity), (3, 3, 4))
        self.assertEqual(
            stats(p1), {"Alpha": (1, 1, 1, 2, 0.5), "Beta": (1, 1, 0, 1, 0.25)}
        )
        self.assertEqual(
            stats(p2), {"Alpha": (3, 2, 1, 2, 0.75), "Beta": (1, 0, 1, 1, 0.25)}
        )
        self.assertEqual(stats(p3), {"Gamma": (1, 1, 0, 1, 1.0)})
        self.assertEqual([s.name for s in p2.themes], ["Alpha", "Beta"])

    def test_untagged_periods_get_no_share(self):
        r = analyze(DOCS, ACTIVITY, PERIODS, DOC_THEMES, {"pr#1"}, NAMES, LINKS)
        p1 = r.periods[1]
        self.assertFalse(p1.covered)  # 1 of 3 documents tagged
        self.assertEqual(stats(p1)["Alpha"][4], None)

    def test_new_themes_only_after_a_covered_period(self):
        r = report()
        # P1 is the first covered period: nothing earlier to compare with.
        self.assertEqual([p.new_known for p in r.periods], [False, False, True, True])
        self.assertEqual([p.new_themes for p in r.periods], [[], [], [], ["Gamma"]])

    def test_trends_compare_last_complete_period_with_earlier(self):
        r = report()
        self.assertEqual((r.recent, r.earlier), (2, [1]))
        self.assertEqual(
            {t.name: t.label for t in r.trends},
            {"Alpha": "rising", "Beta": "steady", "Gamma": "too few"},
        )
        alpha = next(t for t in r.trends if t.name == "Alpha")
        self.assertEqual(
            (alpha.recent_share, alpha.earlier_share, alpha.docs), (0.75, 0.5, 4)
        )

    def test_theme_without_activity_is_steady_not_rising(self):
        quiet = [
            Document("pr", "pr#8", ts(2020, 4), "", ""),
            Document("pr", "pr#9", ts(2021, 4), "", ""),
        ]
        r = analyze(
            DOCS + quiet,
            ACTIVITY,
            PERIODS,
            {**DOC_THEMES, "pr#8": {"D"}, "pr#9": {"D"}},
            TAGGED | {"pr#8", "pr#9"},
            {**NAMES, "D": "Delta"},
            LINKS,
            skip_in_progress=True,
            min_docs=2,
        )
        self.assertEqual({t.name: t.label for t in r.trends}["Delta"], "steady")

    def test_theme_stats_are_ordered_by_activity_then_name(self):
        docs = [
            Document("pr", "pr#1", ts(2020, 3), "", ""),
            Document("pr", "pr#2", ts(2020, 6), "", ""),
        ]
        acts = [
            Activity("a", ts(2020, 3), "pr", "pr#1"),
            Activity("b", ts(2020, 4), "review", "pr#1"),
            Activity("c", ts(2020, 5), "review", "pr#1"),
            Activity("a", ts(2020, 6), "pr", "pr#2"),
            Activity("a", ts(2020, 6), "commit", "cccccccccccc"),
        ]

        def order(names):
            r = analyze(
                docs,
                acts,
                PERIODS,
                {"pr#1": {"X"}, "pr#2": {"Y"}},
                {"pr#1", "pr#2"},
                names,
                {"cccccccccccc": "pr#2"},
            )
            return [s.name for s in r.periods[1].themes]

        # X has 3 activities (1 code, 2 discussion), Y has 2 (both code).
        self.assertEqual(order({"X": "Zulu", "Y": "Alpha"}), ["Zulu", "Alpha"])
        acts[1:3] = []  # both now have 2
        self.assertEqual(order({"X": "Zulu", "Y": "Alpha"}), ["Alpha", "Zulu"])

    def test_period_is_covered_when_exactly_the_coverage_share_is_tagged(self):
        docs = [
            Document("pr", "pr#1", ts(2020, 3), "", ""),
            Document("pr", "pr#2", ts(2020, 6), "", ""),
        ]
        r = analyze(docs, [], PERIODS, {"pr#1": {"X"}}, {"pr#1"}, {"X": "Xray"}, {})
        self.assertEqual([p.covered for p in r.periods], [False, True, False, False])

    def test_min_docs(self):
        labels = {t.name: t.label for t in report(min_docs=5).trends}
        self.assertEqual(labels["Alpha"], "too few")  # 4 documents

    def test_fading(self):
        labels = {t.name: t.label for t in report(rise=3, fade=0.8).trends}
        self.assertEqual(labels["Beta"], "steady")
        labels = {t.name: t.label for t in report(rise=3, fade=1.0).trends}
        self.assertEqual(labels["Beta"], "fading")  # 0.25 <= 1.0 x 0.25

    def test_in_progress_period_counts_when_not_skipped(self):
        r = report(skip_in_progress=False)
        self.assertEqual((r.recent, r.earlier), (3, [1, 2]))

    def test_top_contributors(self):
        r = report()
        self.assertEqual(
            [(c.person, c.code, c.discussion) for c in r.contributors["A"]],
            [("ann", 3, 0), ("bo", 0, 2)],
        )
        # Bo and Cy tie on Beta with 1 each; names break the tie.
        self.assertEqual([c.person for c in r.contributors["B"]], ["bo", "cy"])
        self.assertEqual(len(report(top=1).contributors["A"]), 1)


class LoadersTest(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_doc_themes_skip_merged_themes(self):
        registry = themes.Registry(self.conn)
        a, b = registry.create("Alpha"), registry.create("Alpha old")
        with self.conn:
            self.conn.executemany(
                "INSERT INTO doc_themes VALUES (?, ?)",
                [("pr#1", a), ("pr#2", b)],
            )
            self.conn.execute("INSERT INTO doc_tagging VALUES ('pr#1', 'h', 0)")
        self.conn.execute("UPDATE themes SET merged_into = ? WHERE id = ?", (a, b))
        self.assertEqual(load_doc_themes(self.conn), {"pr#1": {a}})
        self.assertEqual(load_tagged(self.conn), {"pr#1"})
        self.assertEqual(load_theme_names(self.conn), {a: "Alpha"})

    def test_commit_links(self):
        add_item(self.conn, "P5", 5, "pr", "ann", 1)
        self.conn.execute("UPDATE items SET merge_commit_sha = 'aaa' WHERE id = 'P5'")
        for sha, subject in [
            ("aaa", "merged"),
            ("bbb", "squashed (#5)"),
            ("ccc", "unknown (#99)"),
        ]:
            add_commit(self.conn, sha, 1, "Ann", "ann@a.example")
            self.conn.execute(
                "UPDATE commits SET subject = ? WHERE sha = ?", (subject, sha)
            )
        self.assertEqual(commit_links(self.conn), {"aaa": "pr#5", "bbb": "pr#5"})


if __name__ == "__main__":
    unittest.main()
