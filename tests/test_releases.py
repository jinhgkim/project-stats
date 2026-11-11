import tempfile
import unittest
from pathlib import Path

from projstats import gitlog, storage
from projstats.releases import Release, find_releases, import_releases, load_releases
from tests import isolate_git
from tests.test_gitlog import GitRepo

OIIO = r"^(?:Release-|v)(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$"


class FindReleasesTest(unittest.TestCase):
    def test_earliest_final_tag_per_minor_version(self):
        tags = [
            ("Release-1.2.1", 400),
            ("Release-1.2.0", 300),
            ("v1.3.0-beta1", 450),  # not final
            ("spi-Arn3.5.45.0", 460),  # not a release tag
            ("v1.3.6.0", 600),
            ("v1.3.5.1", 550),
            ("v1.3.5.0", 500),
        ]
        self.assertEqual(
            find_releases(tags, OIIO),
            [Release("1.2", "Release-1.2.0", 300), Release("1.3", "v1.3.5.0", 500)],
        )

    def test_same_version_twice_keeps_the_earlier_tag(self):
        tags = [("v2.0.0.0", 900), ("Release-2.0.0", 800)]
        self.assertEqual(
            find_releases(tags, OIIO), [Release("2.0", "Release-2.0.0", 800)]
        )

    def test_sorted_by_date(self):
        tags = [("v2.0.0", 900), ("v1.9.0", 950)]
        self.assertEqual([r.version for r in find_releases(tags, OIIO)], ["2.0", "1.9"])

    def test_optional_patch_counts_as_zero(self):
        pattern = r"^OFX_Release_(\d+)[._](\d+)(?:[._](\d+))?(?:_TAG)?$"
        tags = [
            ("OFX_Release_1_1_1_TAG", 200),
            ("OFX_Release_1_1_TAG", 100),
            ("OFX_Release_1_0_RC6_TAG", 50),  # not final
            ("OFX_Release_1.5s", 400),  # not a release tag
            ("OFX_Release_1.5", 300),
        ]
        self.assertEqual(
            find_releases(tags, pattern),
            [
                Release("1.1", "OFX_Release_1_1_TAG", 100),
                Release("1.5", "OFX_Release_1.5", 300),
            ],
        )


class ImportReleasesTest(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = GitRepo(Path(tmp.name) / "work")
        self.bare = Path(tmp.name) / "mirror.git"
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def tag(self, name):
        self.work.commit(f"work for {name}")
        self.work.run("tag", "-a", name, "-m", name)

    def test_tags_imported_and_new_tags_fetched_on_update(self):
        self.tag("v1.0.0")
        self.tag("v1.0.1")
        gitlog.sync_clone(str(self.work.path), self.bare, blobless=False)
        found = import_releases(self.conn, self.bare, OIIO)
        self.assertEqual([(r.version, r.tag) for r in found], [("1.0", "v1.0.0")])

        self.tag("v1.1.0")
        gitlog.sync_clone(str(self.work.path), self.bare, blobless=False)
        import_releases(self.conn, self.bare, OIIO)
        self.assertEqual(
            [(r.version, r.tag) for r in load_releases(self.conn)],
            [("1.0", "v1.0.0"), ("1.1", "v1.1.0")],
        )
        dates = [r.released_at for r in load_releases(self.conn)]
        self.assertLess(dates[0], dates[1])


if __name__ == "__main__":
    unittest.main()
