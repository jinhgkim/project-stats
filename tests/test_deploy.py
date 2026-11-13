import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from projstats import cli, config, deploy, storage
from tests.test_page import embedded_data

TAG = "https://www.googletagmanager.com/gtm.js?id=G-TEST123"
REPO = Path(__file__).resolve().parent.parent


def set_ga_env(value):
    if value is None:
        os.environ.pop("PROJSTATS_GA_ID", None)
    else:
        os.environ["PROJSTATS_GA_ID"] = value


def write_project(tmp: Path, name: str, db: bool = True) -> None:
    (tmp / f"{name}.toml").write_text(
        f'data_dir = "{(tmp / "data").as_posix()}"\n'
        f'[repo]\ngithub = "org/{name}"\nlabel = "Org {name}"\n'
    )
    if db:
        storage.connect(config.load(tmp / f"{name}.toml").db_path).close()


def write_list(tmp: Path, projects: list[str], index: str) -> Path:
    names = ", ".join(f'"{p}.toml"' for p in projects)
    (tmp / "deploy.toml").write_text(f'projects = [{names}]\nindex = "{index}.toml"\n')
    return tmp / "deploy.toml"


class DeployTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "site"

    def build(self, projects, index, ga_id=None):
        listing = deploy.load_list(write_list(self.tmp, projects, index))
        return deploy.build(listing, self.out, ga_id)

    def test_list_paths_are_relative_to_the_list_file(self):
        listing = deploy.load_list(write_list(self.tmp, ["a", "b"], "b"))
        self.assertEqual(listing.projects, [self.tmp / "a.toml", self.tmp / "b.toml"])
        self.assertEqual(listing.index, self.tmp / "b.toml")

    def test_list_rejects_an_index_that_is_not_listed(self):
        with self.assertRaisesRegex(ValueError, "index must be one of the projects"):
            deploy.load_list(write_list(self.tmp, ["a"], "b"))

    def test_list_rejects_unknown_settings(self):
        (self.tmp / "deploy.toml").write_text(
            'projects = ["a.toml"]\nindex = "a.toml"\nx = 1\n'
        )
        with self.assertRaisesRegex(ValueError, "unknown setting"):
            deploy.load_list(self.tmp / "deploy.toml")

    def test_writes_a_page_per_project_and_index_is_the_chosen_one(self):
        for name in ("a", "b"):
            write_project(self.tmp, name)
        written = self.build(["a", "b"], "b")
        self.assertEqual(
            sorted(p.name for p in written),
            ["index.html", "org__a.html", "org__b.html"],
        )
        index = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(index, (self.out / "org__b.html").read_text(encoding="utf-8"))
        other = (self.out / "org__a.html").read_text(encoding="utf-8")
        self.assertNotEqual(index, other)

    def test_switcher_lists_only_the_listed_projects(self):
        for name in ("a", "b", "unlisted"):
            write_project(self.tmp, name)
        self.build(["a", "b"], "a")
        for name in ("org__a.html", "org__b.html", "index.html"):
            text = (self.out / name).read_text(encoding="utf-8")
            self.assertEqual(
                [s["href"] for s in embedded_data(text)["siblings"]],
                ["org__a.html", "org__b.html"],
            )
        data = embedded_data((self.out / "org__b.html").read_text(encoding="utf-8"))
        self.assertEqual([s["current"] for s in data["siblings"]], [False, True])

    def test_google_tag_is_added_once_and_only_when_asked(self):
        write_project(self.tmp, "a")
        self.build(["a"], "a")
        self.assertNotIn("googletagmanager", (self.out / "index.html").read_text())
        for _ in range(2):
            self.build(["a"], "a", "G-TEST123")
            for name in ("org__a.html", "index.html"):
                text = (self.out / name).read_text(encoding="utf-8")
                self.assertEqual(text.count(TAG), 1)
                head = '<!doctype html>\n<html lang="en">\n<head>\n<script async'
                self.assertTrue(text.startswith(head))

    def test_rejects_a_google_tag_id_that_is_not_one(self):
        write_project(self.tmp, "a")
        for bad in ('G-X"></script><script>', "G-TEST123\n"):
            with (
                self.subTest(bad=bad),
                self.assertRaisesRegex(ValueError, "Google tag ID"),
            ):
                self.build(["a"], "a", bad)

    def test_removes_pages_of_projects_no_longer_listed(self):
        for name in ("a", "b"):
            write_project(self.tmp, name)
        self.build(["a", "b"], "a")
        (self.out / "notes.txt").write_text("keep")
        self.build(["a"], "a")
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            ["index.html", "notes.txt", "org__a.html"],
        )

    def test_missing_database_stops_before_writing_anything(self):
        write_project(self.tmp, "a")
        write_project(self.tmp, "b", db=False)
        with self.assertRaisesRegex(ValueError, "run fetch first"):
            self.build(["a", "b"], "a")
        self.assertFalse(self.out.exists())

    def test_two_listed_projects_cannot_be_the_same_repository(self):
        write_project(self.tmp, "a")
        (self.tmp / "again.toml").write_text((self.tmp / "a.toml").read_text())
        with self.assertRaisesRegex(ValueError, "same repository"):
            self.build(["a", "again"], "a")

    def test_list_rejects_projects_that_are_not_a_list_of_names(self):
        for bad in ("[]", '"a.toml"', "[1]", '[""]'):
            (self.tmp / "deploy.toml").write_text(
                f'projects = {bad}\nindex = "a.toml"\n'
            )
            with (
                self.subTest(bad=bad),
                self.assertRaisesRegex(ValueError, "projects must be a list"),
            ):
                deploy.load_list(self.tmp / "deploy.toml")

    def test_tag_needs_a_head_line_to_follow(self):
        with self.assertRaisesRegex(ValueError, "no <head> line"):
            deploy.add_tag("<html></html>", "G-TEST123")

    def test_the_repository_list_names_configs_that_load(self):
        listing = deploy.load_list(REPO / "deploy.toml")
        self.assertTrue(listing.projects)
        for path in listing.projects:
            config.load(path)

    def run_deploy(self, ga_id):
        self.addCleanup(set_ga_env, os.environ.get("PROJSTATS_GA_ID"))
        set_ga_env(ga_id)
        listing = write_list(self.tmp, ["a"], "a")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["deploy", "--list", str(listing), "--out", str(self.out)])
        return code, out.getvalue()

    def test_command_adds_the_google_tag_when_the_variable_is_set(self):
        write_project(self.tmp, "a")
        code, out = self.run_deploy("G-TEST123")
        self.assertEqual(code, 0)
        self.assertIn("google tag: added", out)
        self.assertIn("org__a.html", out)
        index = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(index.count(TAG), 1)

    def test_command_adds_no_tag_when_the_variable_is_unset_or_empty(self):
        write_project(self.tmp, "a")
        for value in (None, ""):
            with self.subTest(value=value):
                code, out = self.run_deploy(value)
                self.assertEqual(code, 0)
                self.assertIn("not added", out)
                index = (self.out / "index.html").read_text(encoding="utf-8")
                self.assertNotIn("googletagmanager", index)

    def test_command_reports_a_bad_list_and_fails(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["deploy", "--list", str(self.tmp / "missing.toml")])
        self.assertEqual(code, 1)
        self.assertIn("error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
