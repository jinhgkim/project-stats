import json
import re
import tempfile
import unittest
from pathlib import Path

from projstats import page


def embedded_data(text: str) -> dict:
    blob = re.search(
        r'<script id="data" type="application/json">(.*?)</script>', text, re.S
    )
    return json.loads(blob.group(1))


class PageTest(unittest.TestCase):
    def test_scripts_load_core_first_and_check_last(self):
        names = [p.relative_to(page.PAGE_DIR).as_posix() for p in page.js_files()]
        self.assertEqual(names[:2], ["core.js", "metrics.js"])
        self.assertEqual(names[-1], "check.js")
        self.assertIn("filters/kind.js", names)
        views = ("period_counts", "segments", "cohorts", "timeline", "themes_over_time")
        for view in (*views, "theme_table"):
            self.assertIn(f"views/{view}.js", names)
        for name in ("segment_rules", "theme"):
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


if __name__ == "__main__":
    unittest.main()
