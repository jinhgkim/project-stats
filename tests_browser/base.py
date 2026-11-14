import atexit
import os
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from tests_browser import fixture

# One site and one browser for the whole run, started by the first test.
_session = {}


def _start():
    # PROJSTATS_SITE: serve a built site folder instead of the fixture.
    folder = os.environ.get("PROJSTATS_SITE")
    site = fixture.serve(Path(folder)) if folder else fixture.served_site()
    url = site.__enter__()
    play = sync_playwright().start()
    _session.update(site=site, url=url, play=play, browser=play.chromium.launch())


def _stop():
    if not _session:
        return
    _session["browser"].close()
    _session["play"].stop()
    _session["site"].__exit__(None, None, None)
    _session.clear()


atexit.register(_stop)


class BrowserTest(unittest.TestCase):
    def setUp(self):
        if not _session:
            _start()
        self.base = _session["url"]
        self.page = _session["browser"].new_page()
        self.addCleanup(self.page.close)
        # The page's Google tag must not count visits from the tests.
        self.page.route(
            "**/www.googletagmanager.com/**",
            lambda route: route.fulfill(
                status=200, content_type="application/javascript", body=""
            ),
        )
        self.page.set_default_timeout(5000)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on(
            "console",
            lambda m: self.errors.append(m.text) if m.type == "error" else None,
        )

    def open(self, name: str, hash: str = ""):
        self.page.goto(f"{self.base}/org__{name}.html{hash}")
        self.page.wait_for_selector("#tabs .tab")

    def load(self, hash: str):
        # Changing only the hash does not reload the page, so reload to re-read it.
        self.open(fixture.PROJECTS[0], hash)
        self.page.reload()
        self.page.wait_for_selector("#tabs .tab")

    def hash_of(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.page.url).fragment)
