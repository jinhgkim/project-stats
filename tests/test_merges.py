import unittest
from datetime import UTC, datetime

from projstats import merges, storage
from projstats.documents import release_periods
from projstats.releases import Release
from projstats.retention import Activity
from tests.github_rows import add_item


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


def pr(number: int, opened: str) -> Activity:
    return Activity("ann", ts(opened), "pr", f"pr#{number}")


class BucketTest(unittest.TestCase):
    def test_boundaries(self):
        cases = {0: 0, 1: 1, 6: 1, 7: 2, 29: 2, 30: 3, 400: 3}
        for days, index in cases.items():
            with self.subTest(days=days):
                self.assertEqual(merges.bucket(days), index)


class MergeCountsTest(unittest.TestCase):
    def setUp(self):
        self.activity = [
            pr(1, "2024-01-10T23:00"),
            pr(2, "2024-02-01T09:00"),
            pr(3, "2023-12-20T12:00"),
            pr(4, "2024-01-05T12:00"),  # never merged
            pr(5, "2024-06-01T12:00"),
            Activity("bo", ts("2024-01-11T00:30"), "review", "pr#1"),
        ]
        self.merged = {
            "pr#1": ts("2024-01-11T01:00"),  # 2 hours, but the next UTC day
            "pr#2": ts("2024-02-01T17:00"),
            "pr#3": ts("2024-03-30T12:00"),  # 101 days, counted where merged
            "pr#5": ts("2024-07-15T12:00"),
            "pr#9": ts("2024-01-01T12:00"),  # not in the activity (a bot's)
        }

    def rows(self, period, data_end="2024-08-01T00:00"):
        result = merges.merge_counts(self.activity, self.merged, period, ts(data_end))
        return [(r.label, r.counts, r.median, r.partial) for r in result]

    def test_quarters_in_whole_days_with_empty_periods_listed(self):
        self.assertEqual(
            self.rows("quarter"),
            [
                ("2024 Q1", [1, 1, 0, 1], 1, False),
                ("2024 Q2", [0, 0, 0, 0], None, False),
                ("2024 Q3", [0, 0, 0, 1], 44, True),
            ],
        )

    def test_median_of_an_even_count_is_the_mean_of_the_middle_two(self):
        self.activity = [pr(1, "2024-01-01T12:00"), pr(2, "2024-01-02T12:00")]
        self.merged = {"pr#1": ts("2024-01-01T13:00"), "pr#2": ts("2024-01-05T12:00")}
        self.assertEqual(self.rows("year"), [("2024", [1, 1, 0, 0], 1.5, True)])

    def test_release_cycles(self):
        periods = release_periods([Release("1.0", "v1.0.0", ts("2024-03-01T00:00"))])
        self.assertEqual(
            self.rows(periods),
            [
                ("1.0", [1, 1, 0, 0], 0.5, False),
                ("1.1 dev", [0, 0, 0, 2], 72.5, True),
            ],
        )

    def test_no_merges(self):
        self.assertEqual(merges.merge_counts([], self.merged, "year", 0), [])


class LoadMergedTest(unittest.TestCase):
    def test_merged_live_prs_only(self):
        conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        add_item(conn, "P1", 1, "pr", "ann", ts("2024-01-01T00:00"))
        add_item(conn, "P2", 2, "pr", "ann", ts("2024-01-01T00:00"))
        add_item(conn, "P3", 3, "pr", "ann", ts("2024-01-01T00:00"), vanished=1)
        add_item(conn, "I4", 4, "issue", "ann", ts("2024-01-01T00:00"))
        conn.execute(
            "UPDATE items SET merged_at = ? WHERE id IN ('P1', 'P3', 'I4')",
            (ts("2024-01-02T00:00"),),
        )
        self.assertEqual(merges.load_merged(conn), {"pr#1": ts("2024-01-02T00:00")})


if __name__ == "__main__":
    unittest.main()
