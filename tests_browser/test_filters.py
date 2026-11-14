import unittest

from tests_browser import base, fixture

NAME = fixture.PROJECTS[0]

# Rows are Year, Active, New, Returning, Continuing, Activity, worked out from
# the fixture's rows by hand (see fixture.fill).
ALL = [
    ["2019", "1", "1", "0", "0", "1"],
    ["2020", "3", "2", "1", "0", "6"],
    ["2021 (partial)", "2", "1", "0", "1", "2"],
]
CODE = [
    ["2019", "1", "1", "0", "0", "1"],
    ["2020", "2", "1", "1", "0", "3"],
    ["2021 (partial)", "1", "0", "1", "0", "1"],
]
DISCUSSION = [
    ["2020", "3", "3", "0", "0", "3"],
    ["2021 (partial)", "1", "1", "0", "0", "1"],
]
# Tile values: active, new, people doing most of the activity.
TILES = {"All": ["2", "1", "2"], "Code": ["2", "1", "2"], "Discussion": ["1", "1", "0"]}
ROWS = {"All": ALL, "Code": CODE, "Discussion": DISCUSSION}
YEARS = {"All": ["2019", "2020", "2021"], "Code": ["2019", "2020", "2021"]}
YEARS["Discussion"] = ["2020", "2021"]


class FilterTest(base.BrowserTest):
    def rows(self) -> list[list[str]]:
        """The period table without its Last seen column."""
        cells = self.page.locator("#view-period-counts table tbody tr").evaluate_all(
            "rows => rows.map(r => [...r.cells].map(c => c.textContent))"
        )
        return [c[:5] + c[6:] for c in cells]

    def years_on_chart(self) -> list[str]:
        ticks = self.page.locator('#view-period-counts .plot g.axis text[y="8"]')
        return [t.split()[0] for t in ticks.all_text_contents()]

    def tiles(self) -> list[str]:
        return self.page.locator("#view-summary .tile .value").all_text_contents()

    def chips(self) -> list[str]:
        return self.page.locator("#filter-chips .chip").evaluate_all(
            "chips => chips.map(c => c.firstChild.textContent)"
        )

    def choose(self, name: str):
        self.page.click(f"#filter-kind button[data-label={name}]")

    def checked(self) -> list[str]:
        buttons = self.page.locator("#filter-kind button[aria-checked=true]")
        return buttons.all_inner_texts()


class ActivityFilterTest(FilterTest):
    def test_each_choice_changes_the_table_chart_and_tiles(self):
        self.open(NAME, "#period=year")
        for choice in ["Code", "Discussion", "All"]:
            with self.subTest(choice):
                self.choose(choice)
                self.assertEqual(self.checked(), [choice])
                self.assertEqual(self.rows(), ROWS[choice])
                self.assertEqual(self.years_on_chart(), YEARS[choice])
                self.assertEqual(self.tiles(), TILES[choice])
        self.assertEqual(self.errors, [])

    def test_choice_shows_a_chip_that_removes_it(self):
        self.open(NAME, "#period=year")
        self.assertEqual(self.chips(), [])
        self.choose("Code")
        self.assertEqual(self.chips(), ["Activity: Code"])
        self.page.click('#filter-chips [aria-label="Remove filter: Activity: Code"]')
        self.assertEqual(self.chips(), [])
        self.assertEqual(self.checked(), ["All"])
        self.assertEqual(self.rows(), ALL)
        self.assertNotIn("kinds", self.hash_of())

    def test_url_restores_the_choice_and_survives_reload(self):
        self.open(NAME, "#period=year&kinds=review,issue,comment")
        self.assertEqual(self.checked(), ["Discussion"])
        self.assertEqual(self.chips(), ["Activity: Discussion"])
        self.assertEqual(self.rows(), DISCUSSION)
        self.choose("Code")
        self.page.reload()
        self.page.wait_for_selector("#tabs .tab")
        self.assertEqual(self.checked(), ["Code"])
        self.assertEqual(self.rows(), CODE)


class GroupByTest(FilterTest):
    def test_period_sets_how_many_rows_the_table_has(self):
        self.open(NAME)
        for period, count in [("year", 3), ("quarter", 11), ("month", 30)]:
            with self.subTest(period):
                self.page.select_option("#filter-period select", value=period)
                self.assertEqual(len(self.rows()), count)
                self.assertEqual(self.hash_of()["period"], [period])


class DateFilterTest(FilterTest):
    def test_range_includes_both_end_days(self):
        cases = [
            ("2020-05-01", "2020-05-01", "1"),
            ("2020-05-02", "2020-05-02", "1"),
            ("2020-05-01", "2020-05-02", "2"),
            ("2020-05-03", "2020-05-03", None),
        ]
        for start, end, activity in cases:
            with self.subTest(start=start, end=end):
                self.load(f"#period=month&from={start}&to={end}")
                if activity is None:
                    self.assertEqual(self.rows(), [])
                    self.assertEqual(
                        self.page.locator("#view-period-counts .empty").inner_text(),
                        "No activity matches the filters.",
                    )
                else:
                    rows = self.rows()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][5], activity)

    def test_preset_filters_rows_and_fills_the_date_fields(self):
        self.open(NAME, "#period=year")
        self.page.select_option("#filter-dates select", label="Last 3 months")
        self.assertEqual(self.chips(), ["Last 3 months"])
        self.assertEqual(
            self.page.locator('#filter-dates input[aria-label="From"]').input_value(),
            "2021-05-01",
        )
        self.assertEqual(self.rows(), [["2021 (partial)", "1", "1", "0", "0", "1"]])

    def test_typed_date_selects_custom_and_reset_all_clears_every_filter(self):
        self.open(NAME, "#period=year")
        self.page.fill('#filter-dates input[aria-label="From"]', "2020-01-01")
        self.choose("Code")
        self.assertEqual(self.chips(), ["From 2020-01-01", "Activity: Code"])
        self.assertEqual(
            self.page.locator("#filter-dates select").evaluate("s => s.value"),
            "custom",
        )
        self.page.click("#filter-chips .link")
        self.assertEqual(self.chips(), [])
        self.assertEqual(self.checked(), ["All"])
        self.assertEqual(
            self.page.locator("#filter-dates select").evaluate("s => s.value"), "all"
        )
        self.assertEqual(self.rows(), ALL)
        self.assertEqual(self.hash_of(), {"period": ["year"]})


if __name__ == "__main__":
    unittest.main()
