import tempfile
import unittest
from pathlib import Path

from projstats import config


class ConfigTestCase(unittest.TestCase):
    def load(self, text='[repo]\ngithub = "org/proj"\n'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "proj.toml"
        path.write_text(text)
        return config.load(path)


class PathsTest(ConfigTestCase):
    def test_clone_url_defaults_to_github(self):
        self.assertEqual(self.load().clone_url, "https://github.com/org/proj.git")

    def test_clone_url_can_be_overridden(self):
        cfg = self.load('[repo]\ngithub = "org/proj"\nurl = "/srv/proj.git"\n')
        self.assertEqual(cfg.clone_url, "/srv/proj.git")

    def test_paths_live_under_data_dir_and_use_the_slug(self):
        cfg = self.load('data_dir = "d"\n[repo]\ngithub = "org/proj"\n')
        self.assertEqual(cfg.slug, "org__proj")
        self.assertEqual(cfg.clone_path, Path("d/repos/org__proj.git"))
        self.assertEqual(cfg.db_path, Path("d/org__proj.db"))


class ValidationTest(ConfigTestCase):
    def assertRejected(self, text, message):
        with self.assertRaisesRegex(ValueError, message):
            self.load(f'[repo]\ngithub = "org/proj"\n{text}')

    def test_theme_limits_must_be_positive(self):
        for key in ("max_per_doc", "doc_chars", "batch_docs", "batch_chars"):
            with self.subTest(key):
                self.assertRejected(
                    f"[themes]\n{key} = 0\n", r"\[themes\] limits must be at least 1"
                )

    def test_project_names_must_be_a_list_of_names(self):
        for bad in ('"OIIO"', '["OIIO", ""]', "[1]"):
            with self.subTest(bad):
                self.assertRejected(
                    f"[themes]\nproject_names = {bad}\n", "project_names must be a list"
                )

    def test_project_names_are_read(self):
        cfg = self.load(
            '[repo]\ngithub = "o/r"\n'
            '[themes]\nproject_names = ["OIIO", "OpenImageIO"]\n'
        )
        self.assertEqual(cfg.themes.project_names, ["OIIO", "OpenImageIO"])

    def test_tag_pattern_must_be_a_regex(self):
        self.assertRejected('[releases]\ntag_pattern = "("\n', "not a valid regex")

    def test_tag_pattern_must_capture_major_minor_and_patch(self):
        self.assertRejected(
            '[releases]\ntag_pattern = "^v(\\\\d+)\\\\.(\\\\d+)$"\n',
            "must capture major, minor, and patch",
        )

    def test_repo_must_be_owner_slash_name(self):
        for bad in ("proj", "a/b/c", "/proj", "org/"):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, "owner/name"):
                    self.load(f'[repo]\ngithub = "{bad}"\n')

    def test_unknown_settings_are_named(self):
        with self.assertRaisesRegex(ValueError, r"unknown top-level setting\(s\): x"):
            self.load('x = 1\n[repo]\ngithub = "org/proj"\n')
        with self.assertRaisesRegex(ValueError, r"unknown \[themes\] setting\(s\): y"):
            self.load('[repo]\ngithub = "org/proj"\n[themes]\ny = 1\n')

    def test_return_gap_must_be_positive(self):
        self.assertRejected(
            "[retention]\nreturn_gap_days = 0\n", r"\[retention\] needs"
        )


if __name__ == "__main__":
    unittest.main()
