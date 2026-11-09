import json
import re
import tempfile
import unittest
from pathlib import Path

from projstats import config, page


def embedded_data(text: str) -> dict:
    blob = re.search(
        r'<script id="data" type="application/json">(.*?)</script>', text, re.S
    )
    return json.loads(blob.group(1))


class PageTest(unittest.TestCase):
    def test_scripts_load_core_first_and_check_last(self):
        names = [p.relative_to(page.PAGE_DIR).as_posix() for p in page.js_files()]
        self.assertEqual(names[:3], ["core.js", "metrics.js", "charts.js"])
        self.assertEqual(names[-1], "check.js")
        self.assertIn("filters/kind.js", names)
        views = ("summary", "period_counts", "segments", "timeline")
        for view in (*views, "themes_over_time", "theme_table", "activity"):
            self.assertIn(f"views/{view}.js", names)
        for name in ("people", "segment_rules", "theme"):
            self.assertIn(f"filters/{name}.js", names)
        filters = [n for n in names if n.startswith("filters/")]
        self.assertEqual(filters, sorted(filters))
        for path in page.js_files():
            self.assertTrue(path.exists(), path)

    def test_data_round_trips_and_cannot_end_the_script(self):
        data = {"docs": {"title": ["evil </script><script>alert(1)</script>"]}}
        text = page.render(data, "Title <b>")
        self.assertEqual(embedded_data(text), data)
        self.assertNotIn("</script><script>alert", text)
        self.assertIn("<title>Title &lt;b&gt;</title>", text)

    def test_every_script_is_inlined_in_order(self):
        text = page.render({}, "t")
        markers = re.findall(r"/\* ([\w/]+\.js) \*/", text)
        expected = [p.relative_to(page.PAGE_DIR).as_posix() for p in page.js_files()]
        self.assertEqual(markers, expected)
        self.assertLess(text.index("/* core.js */"), text.index("PS.start();"))

    def test_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = page.write({"x": 1}, "t", Path(tmp) / "sub" / "p.html")
            self.assertEqual(embedded_data(out.read_text(encoding="utf-8")), {"x": 1})

    def write_projects(self, tmp: Path, names: list[str]) -> Path:
        data = tmp / "data"
        for name in names:
            (tmp / f"{name}.toml").write_text(
                f'data_dir = "{data.as_posix()}"\n[repo]\ngithub = "org/{name}"\nlabel = "Org {name}"\n'
            )
        return tmp

    def test_siblings_list_built_pages_and_this_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.write_projects(Path(tmp), ["a", "b", "c"])
            (tmp / "data").mkdir()
            (tmp / "data" / "org__b.html").write_text("")
            cfg = config.load(tmp / "a.toml")
            out = tmp / "data" / "org__a.html"
            found = page.siblings(tmp / "a.toml", cfg, out)
            self.assertEqual(
                found,
                [
                    {"name": "a", "href": "org__a.html", "current": True},
                    {"name": "b", "href": "org__b.html", "current": False},
                ],
            )

    def test_siblings_links_are_relative_to_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.write_projects(Path(tmp), ["a", "b"])
            (tmp / "data").mkdir()
            (tmp / "data" / "org__b.html").write_text("")
            cfg = config.load(tmp / "a.toml")
            found = page.siblings(tmp / "a.toml", cfg, tmp / "elsewhere" / "a.html")
            self.assertEqual(found[1]["href"], "../data/org__b.html")

    def test_siblings_skips_configs_that_do_not_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.write_projects(Path(tmp), ["a"])
            (tmp / "broken.toml").write_text("[repo]\ngithub = \"nope\"\n")
            cfg = config.load(tmp / "a.toml")
            found = page.siblings(tmp / "a.toml", cfg, tmp / "data" / "org__a.html")
            self.assertEqual([f["name"] for f in found], ["a"])


if __name__ == "__main__":
    unittest.main()
