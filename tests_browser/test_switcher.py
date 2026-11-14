import re
import unittest

from tests_browser import base, fixture

FIRST, SECOND = fixture.PROJECTS


class SwitcherTest(base.BrowserTest):
    def options(self) -> list[str]:
        return self.page.locator("#project option").all_inner_texts()

    def selected(self) -> str:
        return self.page.locator("#project").evaluate(
            "s => s.options[s.selectedIndex].text"
        )

    def test_lists_the_deployed_projects_in_list_order(self):
        for name in fixture.PROJECTS:
            with self.subTest(name):
                self.open(name)
                self.assertTrue(self.page.locator("#project").is_visible())
                self.assertEqual(self.options(), fixture.PROJECTS)

    def test_unlisted_project_is_not_offered(self):
        self.open(FIRST)
        self.assertNotIn(fixture.UNLISTED, self.options())

    def test_current_project_is_selected(self):
        for name in fixture.PROJECTS:
            with self.subTest(name):
                self.open(name)
                self.assertEqual(self.selected(), name)

    def test_switching_opens_the_other_page_and_keeps_shared_filters(self):
        self.open(FIRST, "#kinds=commit,pr&period=year&without=ann")
        self.assertEqual(self.hash_of()["without"], ["ann"])
        self.page.select_option("#project", label=SECOND)
        self.page.wait_for_url(re.compile(rf"/org__{SECOND}\.html#"))
        self.page.wait_for_selector("#tabs .tab")
        self.assertEqual(self.selected(), SECOND)
        self.assertEqual(self.hash_of(), {"kinds": ["commit,pr"], "period": ["year"]})
        self.assertEqual(self.errors, [])

    def test_choosing_the_current_project_stays_put(self):
        self.open(FIRST, "#period=year&without=ann")
        before = self.page.url
        self.page.select_option("#project", label=FIRST)
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.url, before)
        self.assertEqual(self.hash_of()["without"], ["ann"])


if __name__ == "__main__":
    unittest.main()
