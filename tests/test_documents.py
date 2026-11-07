import unittest
from datetime import UTC, datetime

from projstats import storage
from projstats.documents import (
    Document,
    Period,
    assign,
    clean,
    clean_documents,
    find_boilerplate,
    load_documents,
    release_periods,
    year_periods,
)
from projstats.releases import Release
from tests.github_rows import add_commit, add_item


def ts(year, month=7, day=1):
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


def doc(year, body="", title="t", source="pr", month=7):
    return Document(source, f"{source}#{year}", ts(year, month), title, body)


class CleanTest(unittest.TestCase):
    def test_removes_noise_keeps_inline_code(self):
        body = "\n".join(
            [
                "Uses `image_span` now, see https://example.com/x and #123.",
                "Thanks @someone for the report.",
                "```",
                "Traceback: something_in_a_log",
                "```",
                "<!-- template hint -->",
                "- [x] tested on macos",
                "Signed-off-by: Ann Lee <ann@a.example>",
                "Assisted-by: Some Tool / Some Model",
            ]
        )
        text = clean("fix(exr): handle tiles", body)
        self.assertTrue(text.startswith("fix(exr): handle tiles"))  # prefix kept
        self.assertIn("image_span", text)
        self.assertIn("tested on macos", text)
        for gone in (
            "https",
            "#123",
            "@someone",
            "something_in_a_log",
            "template hint",
            "[x]",
            "Signed-off-by",
            "Assisted-by",
        ):
            self.assertNotIn(gone, text)

    def test_boilerplate_lines_dropped(self):
        text = clean(
            "t",
            "real words\n- [ ] **I have read the guide**",
            {"i have read the guide"},
        )
        self.assertNotIn("guide", text)
        self.assertIn("real words", text)


class BoilerplateTest(unittest.TestCase):
    def test_checklist_variants_count_as_one_line(self):
        variants = [
            "- [x] I have updated the documentation",
            "- [ ] **I have updated the documentation**",
            "- [ ] (N/A) I have updated the documentation",
        ]
        docs = [doc(2020, variants[i % 3] + f"\nunique {i}") for i in range(30)]
        found = find_boilerplate(docs, min_count=20)
        self.assertIn("i have updated the documentation", found)
        self.assertFalse(any(line.startswith("unique") for line in found))

    def test_template_fields_with_varying_values(self):
        docs = [doc(2020, f"* OIIO branch/version: 2.{i}.0") for i in range(25)]
        docs += [
            doc(2020, f"Note: {'a long explanation that differs ' * 3}{i}")
            for i in range(25)
        ]
        found = find_boilerplate(docs, min_count=20)
        self.assertIn("field:oiio branch/version", found)
        self.assertNotIn("field:note", found)

    def test_template_used_for_a_single_year(self):
        docs = [doc(2015, f"text {i}") for i in range(900)]
        docs += [doc(2025, "New template line") for _ in range(6)]
        docs += [doc(2025, f"other {i}") for i in range(94)]
        # 6 of 1000 overall is under 1%, but 6 of 2025's 100 is over 5%.
        self.assertIn("new template line", find_boilerplate(docs))


class LoadDocumentsTest(unittest.TestCase):
    def test_commits_linked_to_prs_are_represented_by_the_pr(self):
        conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        add_item(conn, "P5", 5, "pr", "ann", 1_600_000_000)
        add_item(conn, "P6", 6, "pr", "ann", 1_600_000_000, vanished=1)
        conn.execute("UPDATE items SET merge_commit_sha = 'aaa' WHERE id = 'P5'")
        for sha, subject in [
            ("aaa", "merged via merge commit sha"),
            ("bbb", "squashed (#5)"),
            ("ccc", "mentions an unknown PR (#99)"),
            ("ddd", "plain commit"),
        ]:
            add_commit(conn, sha, 1_600_000_000, "Ann", "ann@a.example")
            conn.execute("UPDATE commits SET subject = ? WHERE sha = ?", (subject, sha))
        refs = sorted(d.ref for d in load_documents(conn))
        self.assertEqual(refs, ["ccc", "ddd", "pr#5"])


class PeriodsTest(unittest.TestCase):
    def test_year_periods_mark_the_last_year_partial(self):
        periods = year_periods([doc(2020), doc(2022)])
        self.assertEqual([p.label for p in periods], ["2020", "2021", "2022"])
        self.assertEqual([p.partial for p in periods], [False, False, True])
        self.assertEqual((periods[0].start, periods[0].end), (ts(2020, 1), ts(2021, 1)))

    def test_release_cycles_are_labeled_by_the_release_they_led_to(self):
        periods = release_periods(
            [Release("1.1", "v1.1.0", ts(2021)), Release("1.0", "v1.0.0", ts(2020))]
        )
        self.assertEqual(
            periods,
            [
                Period("1.0 cycle", None, ts(2020)),
                Period("1.1 cycle", ts(2020), ts(2021)),
                Period("after 1.1", ts(2021), None, partial=True),
            ],
        )

    def test_no_releases(self):
        with self.assertRaisesRegex(ValueError, "tag_pattern"):
            release_periods([])

    def test_assign_puts_documents_in_their_period(self):
        periods = release_periods(
            [Release("1.0", "a", ts(2020)), Release("1.1", "b", ts(2021))]
        )
        docs = [doc(2019), doc(2020, month=1), doc(2020), doc(2022)]
        # Jan 1 2020 is before the 1.0 release (Jul 1 2020): still the 1.0 cycle.
        self.assertEqual(assign(docs, periods), [0, 0, 1, 2])


class CleanDocumentsTest(unittest.TestCase):
    def test_boilerplate_found_per_source(self):
        template = "- [ ] I signed the CLA"
        docs = [doc(2020, f"{template}\nfix {i}") for i in range(25)]
        docs.append(doc(2020, f"{template}\nan issue", source="issue"))
        texts = clean_documents(docs)
        self.assertNotIn("CLA", texts[0])
        self.assertIn("fix 0", texts[0])
        # Only PRs use the template, so the one issue keeps the line.
        self.assertIn("CLA", texts[-1])


if __name__ == "__main__":
    unittest.main()
