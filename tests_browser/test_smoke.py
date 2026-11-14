import re
import unittest

from tests_browser import base, fixture


class SmokeTest(base.BrowserTest):
    def test_each_page_loads_without_console_errors(self):
        for name in fixture.PROJECTS:
            with self.subTest(name):
                self.open(name)
                self.assertEqual(self.page.title(), f"{name} Project Analytics")
                self.assertGreater(self.page.locator("#tabs .tab").count(), 0)
                self.assertEqual(self.errors, [])

    def test_every_tab_renders_without_console_errors(self):
        for name in fixture.PROJECTS:
            with self.subTest(name):
                self.open(name)
                tabs = self.page.locator("#tabs .tab")
                self.assertEqual(tabs.all_inner_texts(), ["Overview", "People"])
                for i in range(tabs.count()):
                    tabs.nth(i).click()
                self.assertEqual(self.errors, [])

    def test_people_timeline_draws_a_row_per_person(self):
        self.open(fixture.PROJECTS[0], "#tab=people")
        rows = self.page.locator("#view-timeline rect.hit")
        self.assertEqual(
            rows.evaluate_all("rs => rs.map(r => r.getAttribute('aria-label'))"),
            [
                "Ann Lee: core, 2019-03-05 to 2021-03-05, "
                "4 activity in 4 quarters, active now",
                "Bo Ray: core, 2020-05-01 to 2020-07-02, 3 activity in 2 quarters",
            ],
        )
        self.assertEqual(self.errors, [])

    def test_index_is_the_first_project(self):
        self.page.goto(f"{self.base}/index.html")
        self.page.wait_for_selector("#tabs .tab")
        self.assertEqual(self.page.title(), f"{fixture.PROJECTS[0]} Project Analytics")

    def test_check_mode_matches_python(self):
        for name in fixture.PROJECTS:
            with self.subTest(name):
                self.open(name, "#check")
                box = self.page.locator("#check-panel .box > span")
                box.wait_for()
                text = box.inner_text()
                m = re.fullmatch(r"#check: (\d+) of (\d+) match Python", text)
                self.assertIsNotNone(m, text)
                self.assertEqual(m.group(1), m.group(2))
                self.assertGreater(int(m.group(2)), 0)
                self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
