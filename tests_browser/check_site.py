"""Checks of a built site that hold whatever the data is, run by the daily
deploy before it publishes. Not named test_*, so `discover` leaves it out.

    PROJSTATS_SITE=site python -m unittest tests_browser.check_site

PROJSTATS_LIST names the deploy list (default deploy.toml).
"""

import os
import re
import unittest
from pathlib import Path

from projstats import config, deploy
from tests_browser import base


class LiveSiteTest(base.BrowserTest):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("PROJSTATS_SITE"):
            raise RuntimeError("set PROJSTATS_SITE to the built site folder")
        listing = deploy.load_list(
            Path(os.environ.get("PROJSTATS_LIST", "deploy.toml"))
        )
        cfgs = [config.load(p) for p in listing.projects]
        cls.slugs = [c.slug for c in cfgs]
        cls.names = [c.repo.github.split("/")[-1] for c in cfgs]
        cls.index_slug = cfgs[listing.projects.index(listing.index)].slug

    def setUp(self):
        super().setUp()
        self.page.set_default_timeout(30000)

    def go(self, slug: str, hash: str = ""):
        self.errors.clear()
        self.page.goto(f"{self.base}/{slug}.html{hash}")
        self.page.wait_for_selector("#tabs .tab")

    def visible(self, selector: str) -> bool:
        return self.page.locator(selector).is_visible()

    def activity_total(self) -> int:
        cells = self.page.locator("#view-period-counts table tbody tr td:last-child")
        return sum(int(t.replace(",", "")) for t in cells.all_text_contents())

    def test_every_page_and_tab_loads_cleanly_and_matches_python(self):
        for slug in self.slugs:
            with self.subTest(slug):
                self.go(slug, "#check")
                box = self.page.locator("#check-panel .box > span")
                box.wait_for()
                m = re.fullmatch(
                    r"#check: (\d+) of (\d+) match Python", box.inner_text()
                )
                self.assertIsNotNone(m, box.inner_text())
                self.assertEqual(m.group(1), m.group(2))
                self.assertGreater(int(m.group(2)), 0)
                tabs = self.page.locator("#tabs .tab")
                for i in range(tabs.count()):
                    tabs.nth(i).click()
                self.assertEqual(self.errors, [])

    def test_index_is_the_index_project(self):
        self.page.goto(f"{self.base}/index.html")
        self.page.wait_for_selector("#tabs .tab")
        index_title = self.page.title()
        self.go(self.index_slug)
        self.assertEqual(self.page.title(), index_title)

    def test_switcher_lists_the_deploy_list_and_each_choice_opens(self):
        for slug, name in zip(self.slugs, self.names, strict=True):
            with self.subTest(slug):
                self.go(slug)
                options = self.page.locator("#project option").all_inner_texts()
                self.assertEqual(options, self.names)
                selected = self.page.locator("#project").evaluate(
                    "s => s.options[s.selectedIndex].text"
                )
                self.assertEqual(selected, name)
        self.go(self.slugs[0])
        for slug, name in zip(self.slugs[1:], self.names[1:], strict=True):
            with self.subTest(opens=slug):
                self.page.select_option("#project", label=name)
                self.page.wait_for_url(re.compile(rf"/{re.escape(slug)}\.html"))
                self.page.wait_for_selector("#tabs .tab")
                self.assertEqual(self.errors, [])

    def test_activity_choices_split_the_total(self):
        for slug in self.slugs:
            with self.subTest(slug):
                self.go(slug, "#period=year")
                everything = self.activity_total()
                self.page.click("#filter-kind button[data-label=Code]")
                code = self.activity_total()
                self.page.click("#filter-kind button[data-label=Discussion]")
                discussion = self.activity_total()
                self.assertGreater(everything, 0)
                self.assertEqual(code + discussion, everything)
                self.page.click("#filter-kind button[data-label=All]")
                self.assertEqual(self.activity_total(), everything)

    def test_date_preset_narrows_the_total_and_reset_restores_it(self):
        for slug in self.slugs:
            with self.subTest(slug):
                self.go(slug, "#period=year")
                everything = self.activity_total()
                self.page.select_option("#filter-dates select", label="Last 3 months")
                narrowed = self.activity_total()
                self.assertLess(narrowed, everything)
                self.page.click("#filter-chips .link")
                self.assertEqual(self.activity_total(), everything)

    def test_panes_open_and_close(self):
        for slug in self.slugs:
            with self.subTest(slug):
                self.go(slug)
                if self.page.locator("#more-toggle").count():
                    toggle = self.page.locator("#more-toggle")
                    was = toggle.get_attribute("aria-expanded")
                    toggle.click()
                    self.assertNotEqual(toggle.get_attribute("aria-expanded"), was)
                    self.assertEqual(self.visible("#filter-more"), was == "false")
                    toggle.click()
                    self.assertEqual(toggle.get_attribute("aria-expanded"), was)

                button = self.page.locator(
                    "#view-period-counts button[data-label=Table]"
                )
                button.click()
                self.assertTrue(self.visible("#view-period-counts table"))
                self.assertFalse(self.visible("#view-period-counts .plot"))
                button.click()
                self.assertFalse(self.visible("#view-period-counts table"))

                column = self.page.locator(
                    "#view-period-counts rect.hit.clickable"
                ).last
                self.assertFalse(self.visible("#details-period-counts"))
                column.click()
                self.assertTrue(self.visible("#details-period-counts"))
                column.click()
                self.assertFalse(self.visible("#details-period-counts"))

                tabs = self.page.locator("#tabs .tab")
                for i in range(tabs.count()):
                    tabs.nth(i).click()
                    self.assertEqual(tabs.nth(i).get_attribute("aria-selected"), "true")
                    panels = self.page.locator("main .panel:not([hidden])")
                    self.assertEqual(panels.count(), 1)
                self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
