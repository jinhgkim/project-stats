import unittest

from tests_browser import base, fixture

NAME = fixture.PROJECTS[0]


class PaneTest(base.BrowserTest):
    def visible(self, selector: str) -> bool:
        return self.page.locator(selector).is_visible()

    def first_line(self, selector: str) -> str:
        return self.page.locator(selector).inner_text().splitlines()[0]

    def names(self, selector: str) -> list[str]:
        return self.page.locator(f"{selector} button.link-button").all_inner_texts()

    def selected_tab(self) -> list[str]:
        return self.page.locator('#tabs [aria-selected="true"]').all_inner_texts()

    def focused_id(self) -> str:
        return self.page.evaluate("document.activeElement.id")


class MoreFiltersTest(PaneTest):
    def test_toggle_collapses_and_reopens_the_extra_filters(self):
        self.open(NAME)
        toggle = self.page.locator("#more-toggle")
        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
        self.assertTrue(self.visible("#filter-more"))
        self.assertTrue(self.visible("#filter-theme"))
        toggle.click()
        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
        self.assertFalse(self.visible("#filter-more"))
        self.assertFalse(self.visible("#filter-theme"))
        toggle.click()
        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
        self.assertTrue(self.visible("#filter-theme"))


class TabsTest(PaneTest):
    def test_clicking_a_tab_swaps_the_panel_and_keeps_it_in_the_url(self):
        self.open(NAME)
        self.assertEqual(self.selected_tab(), ["Overview"])
        self.assertTrue(self.visible("#panel-overview"))
        self.assertFalse(self.visible("#panel-people"))
        self.page.click("#tab-people")
        self.assertEqual(self.selected_tab(), ["People"])
        self.assertFalse(self.visible("#panel-overview"))
        self.assertTrue(self.visible("#panel-people"))
        self.assertEqual(self.hash_of()["tab"], ["people"])
        self.page.click("#tab-overview")
        self.assertEqual(self.selected_tab(), ["Overview"])
        self.assertNotIn("tab", self.hash_of())

    def test_url_opens_the_tab(self):
        self.open(NAME, "#tab=people")
        self.assertEqual(self.selected_tab(), ["People"])
        self.assertTrue(self.visible("#panel-people"))
        self.assertFalse(self.visible("#panel-overview"))

    def test_arrow_home_and_end_keys_move_focus_and_open_tabs(self):
        self.open(NAME)
        self.page.focus("#tab-overview")
        for key, tab in [
            ("ArrowRight", "People"),
            ("ArrowRight", "Overview"),
            ("ArrowLeft", "People"),
            ("Home", "Overview"),
            ("End", "People"),
        ]:
            with self.subTest(key=key, tab=tab):
                self.page.keyboard.press(key)
                self.assertEqual(self.selected_tab(), [tab])
                self.assertEqual(self.focused_id(), f"tab-{tab.lower()}")

    def test_only_the_open_tab_is_in_the_tab_order(self):
        self.open(NAME)
        tabs = self.page.locator("#tabs .tab")
        self.assertEqual(tabs.evaluate_all("ts => ts.map(t => t.tabIndex)"), [0, -1])
        self.page.click("#tab-people")
        self.assertEqual(tabs.evaluate_all("ts => ts.map(t => t.tabIndex)"), [-1, 0])


class SmallPanesTest(PaneTest):
    def test_how_to_read_opens_and_closes(self):
        self.open(NAME)
        howto = self.page.locator("#view-period-counts details.howto")
        body = "#view-period-counts .howto-body"
        self.assertFalse(howto.evaluate("d => d.open"))
        self.assertFalse(self.visible(body))
        howto.locator("summary").click()
        self.assertTrue(howto.evaluate("d => d.open"))
        self.assertTrue(self.visible(body))
        howto.locator("summary").click()
        self.assertFalse(howto.evaluate("d => d.open"))
        self.assertFalse(self.visible(body))

    def test_table_button_swaps_the_chart_and_the_table(self):
        self.open(NAME)
        button = self.page.locator("#view-period-counts button[data-label=Table]")
        table, plot = "#view-period-counts table", "#view-period-counts .plot"
        self.assertEqual(button.get_attribute("aria-pressed"), "false")
        self.assertTrue(self.visible(plot))
        self.assertFalse(self.visible(table))
        button.click()
        self.assertEqual(button.get_attribute("aria-pressed"), "true")
        self.assertFalse(self.visible(plot))
        self.assertTrue(self.visible(table))
        button.click()
        self.assertEqual(button.get_attribute("aria-pressed"), "false")
        self.assertTrue(self.visible(plot))
        self.assertFalse(self.visible(table))


class ColumnDetailsTest(PaneTest):
    DETAILS = "#details-period-counts"

    def column(self, label: str):
        return self.page.locator(
            f'#view-period-counts rect.hit[aria-label^="{label}:"]'
        )

    def test_clicking_a_column_lists_its_people_and_clicking_again_closes(self):
        self.open(NAME, "#period=year")
        self.assertFalse(self.visible(self.DETAILS))
        self.column("2020").click()
        self.assertTrue(self.visible(self.DETAILS))
        self.assertEqual(self.first_line(self.DETAILS), "2020 · 3 people")
        self.assertEqual(self.names(self.DETAILS), ["Bo Ray", "cy", "Ann Lee"])
        self.assertEqual(self.hash_of()["pick"], ["year:2020"])
        self.column("2019").click()
        self.assertEqual(self.first_line(self.DETAILS), "2019 · 1 person")
        self.assertEqual(self.names(self.DETAILS), ["Ann Lee"])
        self.column("2019").click()
        self.assertFalse(self.visible(self.DETAILS))
        self.assertNotIn("pick", self.hash_of())

    def test_close_button_closes(self):
        self.open(NAME, "#period=year&pick=year:2020")
        self.assertTrue(self.visible(self.DETAILS))
        self.page.click(f"{self.DETAILS} >> text=Close")
        self.assertFalse(self.visible(self.DETAILS))
        self.assertNotIn("pick", self.hash_of())

    def test_enter_opens_and_closes_from_the_keyboard(self):
        self.open(NAME, "#period=year")
        self.column("2020").focus()
        self.page.keyboard.press("Enter")
        self.assertTrue(self.visible(self.DETAILS))
        self.assertEqual(self.first_line(self.DETAILS), "2020 · 3 people")
        self.page.keyboard.press("Enter")
        self.assertFalse(self.visible(self.DETAILS))

    def test_changing_the_period_closes_it(self):
        self.open(NAME, "#period=year&pick=year:2020")
        self.assertTrue(self.visible(self.DETAILS))
        self.page.select_option("#filter-period select", value="quarter")
        self.assertFalse(self.visible(self.DETAILS))

    def test_choosing_a_person_opens_their_activity_and_closes_again(self):
        self.open(NAME, "#period=year&pick=year:2020")
        pane = "#view-activity"
        self.assertFalse(self.visible(pane))
        self.page.click(f"{self.DETAILS} button.link-button >> text=Bo Ray")
        self.assertTrue(self.visible(pane))
        self.assertEqual(self.first_line(f"{pane} .head"), "Bo Ray")
        self.assertEqual(self.page.locator(f"{pane} tbody tr").count(), 3)
        self.page.click(f"{pane} >> text=Close")
        self.assertFalse(self.visible(pane))
        self.assertNotIn("who", self.hash_of())

    def test_person_pane_needs_an_open_column_of_the_current_period(self):
        cases = [
            ("#period=year&pick=year:2020&who=0", True),
            ("#period=year&who=0", False),
            ("#period=quarter&pick=year:2020&who=0", False),
        ]
        for hash, shown in cases:
            with self.subTest(hash):
                self.load(hash)
                self.assertEqual(self.visible("#view-activity"), shown)


class SegmentsTest(PaneTest):
    DETAILS = "#details-segments"

    def segment(self, name: str):
        return self.page.locator(f'#view-segments rect.hit[aria-label^="{name}:"]')

    def test_core_list_starts_open_and_each_segment_toggles_its_own_list(self):
        self.open(NAME, "#tab=people")
        self.assertEqual(
            self.first_line(self.DETAILS), "Core · 2 people · 77.8% of activity"
        )
        self.assertEqual(self.names(self.DETAILS), ["Ann Lee", "Bo Ray"])
        self.segment("One-time").click()
        self.assertEqual(
            self.first_line(self.DETAILS), "One-time · 2 people · 22.2% of activity"
        )
        self.assertEqual(self.names(self.DETAILS), ["cy", "dee"])
        self.segment("One-time").click()
        self.assertFalse(self.visible(self.DETAILS))
        self.assertEqual(self.hash_of()["list"], ["none"])
        self.segment("Core").click()
        self.assertEqual(
            self.first_line(self.DETAILS), "Core · 2 people · 77.8% of activity"
        )

    def test_close_button_closes_the_list(self):
        self.open(NAME, "#tab=people")
        self.page.click(f"{self.DETAILS} >> text=Close")
        self.assertFalse(self.visible(self.DETAILS))


class PersonPaneTest(PaneTest):
    PANE = "#view-people-activity"

    def expanded(self, view: str) -> list[str]:
        buttons = self.page.locator(f"{view} button.link-button")
        return buttons.evaluate_all("bs => bs.map(b => b.ariaExpanded)")

    def test_choosing_a_person_opens_their_pane_in_every_list_and_closes_again(self):
        self.open(NAME, "#tab=people")
        self.assertFalse(self.visible(self.PANE))
        ann = "#details-segments button.link-button >> text=Ann Lee"
        self.page.click(ann)
        self.assertTrue(self.visible(self.PANE))
        self.assertEqual(self.first_line(f"{self.PANE} .head"), "Ann Lee")
        self.assertEqual(self.page.locator(f"{self.PANE} tbody tr").count(), 4)
        self.assertEqual(self.expanded("#view-segments"), ["true", "false"])
        self.assertEqual(self.expanded("#view-timeline"), ["true", "false"])
        self.assertIn("pwho", self.hash_of())
        self.page.click(ann)
        self.assertFalse(self.visible(self.PANE))
        self.assertEqual(self.expanded("#view-segments"), ["false", "false"])
        self.assertNotIn("pwho", self.hash_of())

    def test_close_button_closes_the_pane(self):
        self.open(NAME, "#tab=people&pwho=0")
        self.assertTrue(self.visible(self.PANE))
        self.page.click(f"{self.PANE} >> text=Close")
        self.assertFalse(self.visible(self.PANE))
        self.assertEqual(self.expanded("#view-segments"), ["false", "false"])


if __name__ == "__main__":
    unittest.main()
