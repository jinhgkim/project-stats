"""Retention math on a hand-counted fixture (all times UTC).

  A  2020-01-15, 2020-02-10, 2021-06-01   gap of 477 days -> returns in 2021
  B  2020-03-01                           one-time
  C  2020-12-31 23:00, 2021-01-02 00:00   crosses a year boundary
  D  2019-06-01, 2022-03-01               returns in 2022; data ends here

Yearly:
  2019  active 1: D new
  2020  active 3: A, B, C new                   activity 4
  2021  active 2: A returning, C continuing     activity 2
  2022  active 1: D returning (partial)
Last seen: B in 2020 (shown: 2020 ended 424 days before the data end);
A and C in 2021 and D in 2022 are too recent, so None.
"""

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from projstats import config, identity, storage
from projstats.config import RetentionConfig
from projstats.documents import Period
from projstats.retention import (
    Activity,
    cohorts,
    exclude_items,
    load_activity,
    load_commit_activity,
    period_bounds,
    period_counts,
    period_key,
    period_label,
    person_stats,
    segments,
)
from tests.github_rows import add_commit, add_commit_login, add_event, add_item

CFG = RetentionConfig(return_gap_days=365, core_share=0.80, regular_share=0.95)


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


FIXTURE = [
    ("A", "2020-01-15"),
    ("A", "2020-02-10"),
    ("A", "2021-06-01"),
    ("B", "2020-03-01"),
    ("C", "2020-12-31T23:00"),
    ("C", "2021-01-02"),
    ("D", "2019-06-01"),
    ("D", "2022-03-01"),
]
ACTIVITY = [Activity(p, ts(t), "commit", f"{p}{i}") for i, (p, t) in enumerate(FIXTURE)]


def table(period: str):
    """{label: (active, new, returning, continuing, last_seen, activity)}"""
    return {
        r.label: (r.active, r.new, r.returning, r.continuing, r.last_seen, r.activity)
        for r in period_counts(ACTIVITY, period, 365)
    }


class PeriodHelpersTest(unittest.TestCase):
    def test_keys_labels_bounds(self):
        t = ts("2021-05-20")
        self.assertEqual(period_label(period_key(t, "month"), "month"), "2021-05")
        self.assertEqual(period_label(period_key(t, "quarter"), "quarter"), "2021 Q2")
        self.assertEqual(period_label(period_key(t, "year"), "year"), "2021")
        q = period_key(t, "quarter")
        self.assertEqual(
            period_bounds(q, "quarter"), (ts("2021-04-01"), ts("2021-07-01"))
        )
        self.assertEqual(
            period_key(ts("2020-12-31T23:59"), "quarter") + 1,
            period_key(ts("2021-01-01"), "quarter"),
        )

    def test_bounds_wrap_the_year(self):
        q4 = period_key(ts("2020-11-01"), "quarter")
        self.assertEqual(period_bounds(q4, "quarter")[1], ts("2021-01-01"))
        dec = period_key(ts("2020-12-05"), "month")
        self.assertEqual(period_bounds(dec, "month")[1], ts("2021-01-01"))


class PeriodCountsTest(unittest.TestCase):
    def test_yearly(self):
        self.assertEqual(
            table("year"),
            {
                "2019": (1, 1, 0, 0, 0, 1),
                "2020": (3, 3, 0, 0, 1, 4),
                "2021": (2, 0, 1, 1, None, 2),
                "2022": (1, 0, 1, 0, None, 1),
            },
        )

    def test_quarterly(self):
        rows = table("quarter")
        self.assertEqual(len(rows), 12)  # 2019 Q2 .. 2022 Q1, empty ones included
        self.assertEqual(rows["2019 Q2"], (1, 1, 0, 0, 0, 1))
        self.assertEqual(rows["2019 Q3"], (0, 0, 0, 0, 0, 0))
        self.assertEqual(rows["2020 Q1"], (2, 2, 0, 0, 1, 3))
        self.assertEqual(rows["2020 Q4"], (1, 1, 0, 0, 0, 1))
        self.assertEqual(rows["2021 Q1"], (1, 0, 0, 1, None, 1))  # ends 334d before
        self.assertEqual(rows["2021 Q2"], (1, 0, 1, 0, None, 1))  # ends < 365d before
        self.assertEqual(rows["2022 Q1"], (1, 0, 1, 0, None, 1))

    def test_monthly(self):
        rows = table("month")
        self.assertEqual(rows["2020-01"][:4], (1, 1, 0, 0))
        self.assertEqual(rows["2020-02"][:4], (1, 0, 0, 1))  # A, 26 days later
        self.assertEqual(rows["2020-03"][:4], (1, 1, 0, 0))
        self.assertEqual(rows["2020-12"][:4], (1, 1, 0, 0))
        self.assertEqual(rows["2021-01"][:4], (1, 0, 0, 1))  # C, a day later
        self.assertEqual(rows["2021-06"][:4], (1, 0, 1, 0))
        self.assertEqual(rows["2022-03"][:4], (1, 0, 1, 0))

    def test_only_last_period_is_partial(self):
        rows = period_counts(ACTIVITY, "year", 365)
        self.assertEqual([r.partial for r in rows], [False, False, False, True])

    def test_empty(self):
        self.assertEqual(period_counts([], "year", 365), [])

    def test_release_cycles(self):
        # B's activity falls on the 1.1 release day, so it counts in the next cycle.
        cycles = [
            Period("1.0 cycle", None, ts("2020-03-01")),
            Period("1.1 cycle", ts("2020-03-01"), ts("2021-01-01")),
            Period("after 1.1", ts("2021-01-01"), None, partial=True),
        ]
        rows = period_counts(ACTIVITY, cycles, 365)
        self.assertEqual(
            [
                (
                    r.label,
                    r.active,
                    r.new,
                    r.returning,
                    r.continuing,
                    r.last_seen,
                    r.activity,
                    r.partial,
                )
                for r in rows
            ],
            [
                ("1.0 cycle", 2, 2, 0, 0, 0, 3, False),  # D, A
                ("1.1 cycle", 2, 2, 0, 0, 1, 2, False),  # B, C; B last seen
                ("after 1.1", 3, 0, 2, 1, None, 3, True),  # C continues; A, D return
            ],
        )
        self.assertEqual((rows[0].start, rows[2].end), (None, None))


class ExcludeItemsTest(unittest.TestCase):
    def test_drops_the_item_and_its_linked_commits(self):
        activity = [
            Activity("A", 1, "commit", "c1"),
            Activity("A", 2, "commit", "c2"),
            Activity("A", 3, "pr", "pr#5"),
            Activity("B", 4, "review", "pr#5"),
            Activity("B", 5, "comment", "issue#6"),
            Activity("B", 6, "issue", "issue#7"),
        ]
        links = {"c1": "pr#5", "c2": "pr#9"}
        got = exclude_items(activity, [5, 7], links)
        self.assertEqual([a.item for a in got], ["c2", "issue#6"])
        self.assertEqual(exclude_items(activity, [], links), activity)


class ActivityConfigTest(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        tmp.write('[repo]\ngithub = "o/r"\n' + text)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def test_reads_numbers(self):
        cfg = config.load(self.write("[activity]\nexclude_items = [3905, 12]\n"))
        self.assertEqual(cfg.activity.exclude_items, [3905, 12])
        self.assertEqual(config.load(self.write("")).activity.exclude_items, [])

    def test_leave_out_option_maps_labels_to_logins(self):
        cfg = config.load(self.write('[people]\nleave_out_option = { maintainer = "lgritz" }\n'))
        self.assertEqual(cfg.people.leave_out_option, {"maintainer": "lgritz"})
        self.assertEqual(config.load(self.write("")).people.leave_out_option, {})
        for bad in ('["lgritz"]', '"lgritz"', '{ maintainer = 1 }', '{ maintainer = "" }', '{ " " = "x" }'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.load(self.write(f"[people]\nleave_out_option = {bad}\n"))

    def test_segment_shares_must_be_ordered(self):
        bad = "[retention]\ncore_share = 0.9\nregular_share = 0.8\n"
        with self.assertRaises(ValueError):
            config.load(self.write(bad))

    def test_rejects_non_numbers(self):
        for bad in ('["pr#5"]', "[0]", "5", "[true]"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.load(self.write(f"[activity]\nexclude_items = {bad}\n"))


class PersonStatsTest(unittest.TestCase):
    def test_fixture_people(self):
        stats = {s.person: s for s in person_stats(ACTIVITY, CFG)}
        a = stats["A"]
        self.assertEqual(
            (a.activity, a.months, a.quarters, a.years), (3, 3, 2, (2020, 2021))
        )
        # 8 activities: A 3, C 2, D 2 reach 80% (7); B has one.
        self.assertEqual((a.longest_gap_days, a.returns, a.segment), (477, 1, "core"))
        self.assertEqual(stats["B"].segment, "one-time")
        self.assertEqual(stats["C"].longest_gap_days, 1)
        self.assertEqual(stats["C"].returns, 0)
        self.assertEqual(stats["D"].returns, 1)
        # Data ends 2022-03-01: A was 273 days earlier, C 423 days, D on that day.
        self.assertEqual(
            {p: s.current for p, s in stats.items()},
            {"A": True, "B": False, "C": False, "D": True},
        )

    def test_segments_by_share(self):
        # 100 activities. Running total: a 50, b 70, c 80 -> core reaches 80%
        # at c (10), and d ties with c. Then e reaches 95%; f is casual.
        counts = {"a": 50, "b": 20, "c": 10, "d": 10, "e": 5, "f": 3, "g": 1, "h": 1}
        self.assertEqual(
            segments(counts, CFG),
            {
                "a": "core",
                "b": "core",
                "c": "core",
                "d": "core",
                "e": "regular",
                "f": "casual",
                "g": "one-time",
                "h": "one-time",
            },
        )

    def test_one_time_comes_first(self):
        # The 80% cutoff falls on people with one activity; they stay one-time.
        self.assertEqual(
            segments({"a": 1, "b": 1}, CFG), {"a": "one-time", "b": "one-time"}
        )

    def test_segments_follow_the_activity_given(self):
        stats = person_stats(
            [Activity("x", ts("2020-01-01"), "commit", str(i)) for i in range(9)]
            + [Activity("y", ts("2020-01-02"), "review", "r")] * 2,
            CFG,
        )
        self.assertEqual(
            {s.person: s.segment for s in stats}, {"x": "core", "y": "regular"}
        )


class CohortsTest(unittest.TestCase):
    def test_fixture_cohorts(self):
        stats = person_stats(ACTIVITY, CFG)
        result = {c.year: c for c in cohorts(stats, ts("2022-03-01"))}
        self.assertEqual(sorted(result), [2019, 2020])
        c19, c20 = result[2019], result[2020]
        self.assertEqual((c19.size, c19.one_time), (1, 0))
        self.assertEqual(c19.active_after, {1: 0, 2: 0, 5: None})  # 2024 not complete
        self.assertEqual((c20.size, c20.one_time), (3, 1))
        self.assertEqual(c20.active_after, {1: 2, 2: None, 5: None})


class LoadCommitActivityTest(unittest.TestCase):
    def test_coauthors_credited_once_per_person_and_bots_skipped(self):
        conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        commits = [
            ("c1", 100, "Ann Lee", "ann@a.example"),
            ("c2", 200, "Ann Lee", "ann@b.example"),
            ("c3", 300, "Copilot", "9+copilot@users.noreply.github.com"),
        ]
        conn.executemany(
            "INSERT INTO commits VALUES (?, ?, ?, ?, ?, ?, ?, '', '')",
            [(sha, t, t, n, e, n, e) for sha, t, n, e in commits],
        )
        coauthors = [
            ("c2", "Ann Lee", "ann@a.example"),  # same person as the author
            ("c2", "Bo Ma", "bo@b.example"),
            ("c3", "Bo Ma", "bo@b.example"),
        ]
        conn.executemany(
            "INSERT INTO commit_coauthors VALUES (?, ?, ?, ?, ?)",
            [(sha, n, e, n, e) for sha, n, e in coauthors],
        )
        people = identity.group_people(identity.load_identities(conn), ["Copilot"])
        got = [(a.person, a.item) for a in load_commit_activity(conn, people)]
        self.assertEqual(
            got,
            [
                ("ann@a.example", "c1"),
                ("ann@a.example", "c2"),
                ("bo@b.example", "c2"),
                ("bo@b.example", "c3"),
            ],
        )


class LoadActivityTest(unittest.TestCase):
    def setUp(self):
        conn = self.conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        add_commit(conn, "c1", 100, "Ann Lee", "ann@a.example")
        add_commit_login(conn, "c1", "ann@a.example", "ann")
        add_item(conn, "P1", 5, "pr", "ann", 200)
        add_item(conn, "I1", 6, "issue", "bo", 300)
        add_event(conn, "R1", "P1", "review", "bo", 400)
        add_event(conn, "C1", "I1", "comment", "Ann", 500)
        add_event(conn, "C2", "I1", "comment", "bo", 600, vanished=999)
        add_event(conn, "C3", "I1", "comment", None, 700)  # ghost
        add_event(conn, "C4", "I1", "comment", "dependabot[bot]", 800)
        self.people = identity.group_people(
            identity.load_identities(conn),
            links=identity.load_links(conn),
            github_logins=identity.load_github_logins(conn),
        )

    def load(self, kinds=None):
        return [
            (a.person, a.ts, a.kind, a.item)
            for a in load_activity(self.conn, self.people, kinds)
        ]

    def test_all_kinds(self):
        self.assertEqual(
            self.load(),
            [
                ("ann@a.example", 100, "commit", "c1"),
                ("ann@a.example", 200, "pr", "pr#5"),
                ("login:bo", 300, "issue", "issue#6"),
                ("login:bo", 400, "review", "pr#5"),
                ("ann@a.example", 500, "comment", "issue#6"),
            ],
        )

    def test_kinds_filter(self):
        self.assertEqual(
            [k for _, _, k, _ in self.load(["review", "comment"])],
            ["review", "comment"],
        )

    def test_unknown_kind(self):
        with self.assertRaisesRegex(ValueError, "nope"):
            self.load(["commit", "nope"])


if __name__ == "__main__":
    unittest.main()
