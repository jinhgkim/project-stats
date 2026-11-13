"""Commands run through cli.main against a temp project and a real database."""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from projstats import cli, config, github, storage
from projstats.themes import Registry
from tests import isolate_git
from tests.github_rows import add_commit, add_commit_login, add_event, add_item
from tests.test_github import FakeClient, comment, commit, iso, item, page, review
from tests.test_gitlog import MAILMAP, GitRepo
from tests.test_llm import StubOllama, unused_port

EXR_REPLY = json.dumps(
    {
        "documents": [{"id": "d1", "themes": ["OpenEXR support"]}],
        "new_themes": [{"name": "OpenEXR support", "description": "EXR files"}],
    }
)
TS = 1_577_923_200  # 2020-01-02 UTC


class CliTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.path = self.tmp / "proj.toml"
        self.write_config()

    def write_config(self, extra="", url=""):
        url_line = f'url = "{url}"\n' if url else ""
        self.path.write_text(
            f'data_dir = "{(self.tmp / "data").as_posix()}"\n'
            f'[repo]\ngithub = "org/proj"\n{url_line}{extra}'
        )
        self.cfg = config.load(self.path)

    def connect(self):
        conn = storage.connect(self.cfg.db_path)
        self.addCleanup(conn.close)
        return conn

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([args[0], str(self.path), *args[1:]])
        return code, out.getvalue(), err.getvalue()

    def add_pr(self, conn, number, title, created=TS):
        add_item(conn, f"pr{number}", number, "pr", "octo", created)
        conn.execute("UPDATE items SET title = ? WHERE number = ?", (title, number))
        conn.commit()


class GitProjectTestCase(CliTestCase):
    def setUp(self):
        super().setUp()
        isolate_git(self)
        self.work = GitRepo(self.tmp / "work")
        self.c1 = self.work.commit(
            "first", {".mailmap": MAILMAP, "a.txt": "a"}, author=("Alice", "a@old.x")
        )
        self.work.run("tag", "v1.0.0")
        self.write_config(url=str(self.work.path))


class GithubFetchTest(GitProjectTestCase):
    def pages(self, prs=()):
        issue = item("I1", 2, "01-20")
        history = commit(self.c1, ("a@old.x", "Alice", "alice"))
        return {
            ("pr", None): page(list(prs)),
            ("issue", None): page([issue]),
            ("history", None): page([history]),
        }

    def pr(self):
        return item(
            "P1",
            1,
            "01-20",
            comments=[comment("C1")],
            reviews=[review("R1")],
            state="MERGED",
            merged=iso("01-04"),
            sha=self.c1,
        )

    def fetch(self, client, full=False):
        args = argparse.Namespace(config=str(self.path), no_github=False, full=full)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli.cmd_fetch(args, client=client)
        finally:
            self.out = out.getvalue()

    def test_fetches_prs_issues_and_commit_logins(self):
        self.fetch(FakeClient(self.pages([self.pr()])))
        lines = self.out.splitlines()
        self.assertIn("PRs: 1 fetched; stored 1 merged", lines)
        self.assertIn("issues: 1 fetched; stored 1 open", lines)
        self.assertIn("events: 2 fetched; stored 1 reviews, 1 comments", lines)
        self.assertIn("commit logins: 1 commits fetched", lines)
        self.assertIn("github api: 3 queries, cost 3, 4000 left (resets soon)", lines)
        conn = self.connect()
        self.assertEqual(
            [tuple(r) for r in conn.execute("SELECT sha, login FROM commit_logins")],
            [(self.c1, "alice")],
        )

    def test_full_reports_what_vanished(self):
        self.fetch(FakeClient(self.pages([self.pr()])))
        self.fetch(FakeClient(self.pages()), full=True)
        self.assertIn("PRs: 0 fetched; stored none; 1 newly vanished", self.out)

    def test_stats_are_printed_even_when_the_budget_runs_out(self):
        with self.assertRaises(github.GitHubError):
            self.fetch(FakeClient(self.pages(), remaining=10))
        self.assertIn("github api: 1 queries", self.out)


class FetchTest(GitProjectTestCase):
    def test_clones_and_imports_history_and_releases(self):
        code, out, _ = self.run_cli("fetch", "--no-github")
        self.assertEqual(code, 0)
        self.assertIn("cloned", out)
        self.assertIn(self.c1[:7], out)
        conn = self.connect()
        self.assertEqual(
            [r[0] for r in conn.execute("SELECT sha FROM commits")], [self.c1]
        )
        self.assertEqual(
            [tuple(r) for r in conn.execute("SELECT version, tag FROM releases")],
            [("1.0", "v1.0.0")],
        )

    def test_rerun_updates_and_finds_nothing_new(self):
        self.run_cli("fetch", "--no-github")
        code, out, _ = self.run_cli("fetch", "--no-github")
        self.assertEqual(code, 0)
        self.assertIn("updated", out)
        self.assertIn("0 new, 1 total", out)
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0], 1)

    def test_says_when_no_tag_matches(self):
        self.write_config(
            '[releases]\ntag_pattern = "^rel-(\\\\d+)\\\\.(\\\\d+)\\\\.(\\\\d+)$"\n',
            url=str(self.work.path),
        )
        _, out, _ = self.run_cli("fetch", "--no-github")
        self.assertIn("none match", out)
        self.assertEqual(
            self.connect().execute("SELECT COUNT(*) FROM releases").fetchone()[0], 0
        )

    def test_rewritten_history_is_reported(self):
        self.work.commit("second")
        self.run_cli("fetch", "--no-github")
        self.work.run("reset", "-q", "--hard", self.c1)
        self.work.commit("replacement")
        _, out, _ = self.run_cli("fetch", "--no-github")
        self.assertIn("rewritten", out)
        subjects = self.connect().execute(
            "SELECT subject FROM commits ORDER BY authored_at"
        )
        self.assertEqual([r[0] for r in subjects], ["first", "replacement"])

    def test_mailmap_change_is_reported(self):
        self.run_cli("fetch", "--no-github")
        self.work.commit(
            "update mailmap", {".mailmap": "Alice S. <a@newest.x> <a@old.x>\n"}
        )
        _, out, _ = self.run_cli("fetch", "--no-github")
        self.assertIn("re-mapped", out)
        row = (
            self.connect()
            .execute("SELECT author_name FROM commits WHERE sha = ?", (self.c1,))
            .fetchone()
        )
        self.assertEqual(row[0], "Alice S.")

    def test_failed_git_command_is_an_error(self):
        self.write_config(url=str(self.tmp / "missing"))
        code, _, err = self.run_cli("fetch", "--no-github")
        self.assertEqual(code, 1)
        self.assertIn("error: `git clone --bare --quiet ...` failed:\nfatal: ", err)


class PrintGithubTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.add_pr(self.conn, 1, "a")
        self.add_pr(self.conn, 2, "b")
        self.conn.execute("UPDATE items SET state = 'merged' WHERE number = 2")
        add_event(self.conn, "e1", "pr1", "review", "octo", TS)
        add_event(self.conn, "e2", "pr1", "comment", "octo", TS)
        add_event(self.conn, "e3", "pr1", "comment", "octo", TS)
        self.stats = github.FetchStats(
            fetched={"pr": 2},
            vanished={"pr": 1},
            events=3,
            commits=5,
            queries=4,
            cost=6,
            remaining=4990,
            reset_at="2020-01-01T01:00Z",
        )

    def printed(self, full):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_github(self.conn, self.stats, full)
        return out.getvalue().splitlines()

    def test_summarizes_what_was_fetched_and_stored(self):
        self.assertEqual(
            self.printed(full=False),
            [
                "PRs: 2 fetched; stored 1 merged, 1 open",
                "events: 3 fetched; stored 1 reviews, 2 comments",
                "commit logins: 5 commits fetched",
                "github api: 4 queries, cost 6, 4990 left (resets 2020-01-01T01:00Z)",
            ],
        )

    def test_full_fetch_adds_newly_vanished(self):
        self.assertEqual(
            self.printed(full=True)[0],
            "PRs: 2 fetched; stored 1 merged, 1 open; 1 newly vanished",
        )

    def test_lists_only_kinds_that_were_fetched(self):
        self.stats.fetched = {"issue": 0}
        self.assertEqual(self.printed(full=False)[0], "issues: 0 fetched; stored none")


class PeopleTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        add_commit(self.conn, "c1", TS, "Ann Lee", "ann@a.example")
        add_commit(self.conn, "c2", TS, "ann lee", "ann@b.example")
        add_commit(self.conn, "c3", TS, "Robo Cop", "robo@a.example")
        self.conn.commit()

    def test_lists_merged_people_and_dropped_bots(self):
        self.write_config('[people]\nbots = ["robo@a.example"]\n')
        code, out, _ = self.run_cli("people")
        self.assertEqual(code, 0)
        self.assertIn("people: 1 (1 with commits, 0 of them linked", out)
        self.assertIn("merged (1):", out)
        self.assertIn("[name 'ann lee']", out)
        self.assertIn("      ann@a.example", out)
        self.assertIn("bots dropped (1):", out)
        self.assertIn("Robo Cop  robo@a.example", out)

    def test_reports_same_person_entries_that_match_nothing(self):
        self.write_config(
            '[[people.same_person]]\nlogin = "ghost"\nemails = ["no@one.example"]\n'
        )
        _, out, _ = self.run_cli("people")
        self.assertIn("same_person entries that match nothing (2):", out)
        self.assertIn("no@one.example: no commits with this email", out)
        self.assertIn("ghost: no GitHub activity", out)

    def test_counts_people_who_only_appear_on_github(self):
        self.add_pr(self.conn, 1, "Add EXR tiles")
        _, out, _ = self.run_cli("people")
        self.assertIn(
            "people: 3 (2 with commits, 0 of them linked to a GitHub login; "
            "1 GitHub-only)",
            out,
        )

    def test_counts_commit_authors_linked_to_a_login(self):
        add_commit_login(self.conn, "c1", "ann@a.example", "annlee")
        self.conn.commit()
        _, out, _ = self.run_cli("people")
        self.assertIn("1 of them linked to a GitHub login", out)


class ThemesTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.add_pr(self.conn, 1, "Add EXR tiles", created=TS)
        self.add_pr(self.conn, 2, "Fix EXR header", created=TS + 86_400)
        registry = Registry(self.conn)
        exr = registry.create("OpenEXR support")
        registry.create("Python wheels")
        registry.add_alias(exr, "EXR")
        with self.conn:
            self.conn.executemany(
                "INSERT INTO doc_themes VALUES (?, ?)",
                [("pr#1", exr), ("pr#2", exr)],
            )

    def docs_of(self, name):
        theme_id = Registry(self.conn).lookup(name)
        rows = self.conn.execute(
            "SELECT doc_ref FROM doc_themes WHERE theme_id = ? ORDER BY doc_ref",
            (theme_id,),
        )
        return [r[0] for r in rows]

    def names(self):
        return sorted(Registry(self.conn).names.values())

    def test_an_action_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                self.run_cli("themes")
        self.assertEqual(raised.exception.code, 2)

    def test_list_is_empty_before_tagging(self):
        self.conn.execute("DELETE FROM doc_themes")
        self.conn.execute("DELETE FROM themes")
        self.conn.commit()
        code, out, _ = self.run_cli("themes", "list")
        self.assertEqual(code, 0)
        self.assertIn("themes: none yet; run `projstats tag` first", out)

    def test_list_shows_counts_dates_and_aliases_most_used_first(self):
        code, out, _ = self.run_cli("themes", "list")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "themes: 2")
        self.assertEqual(
            lines[2], "      2  2020-01-02  2020-01-03  OpenEXR support  (also: EXR)"
        )
        self.assertEqual(lines[3], "      0  -           -           Python wheels")

    def test_list_shows_100_rows_by_default(self):
        registry = Registry(self.conn)
        for i in range(101):
            registry.create(f"Extra {i:03d}")
        _, out, _ = self.run_cli("themes", "list")
        lines = out.splitlines()
        self.assertEqual(lines[0], "themes: 103")
        self.assertEqual(len(lines) - 2, 100)

    def test_list_top_limits_rows(self):
        _, out, _ = self.run_cli("themes", "list", "--top", "1")
        self.assertIn("OpenEXR support", out)
        self.assertNotIn("Python wheels", out)

    def test_rename_keeps_the_old_name_as_an_alias(self):
        code, out, _ = self.run_cli("themes", "rename", "Python wheels", "Wheels")
        self.assertEqual(code, 0)
        self.assertIn("Wheels", out)
        self.assertEqual(self.names(), ["OpenEXR support", "Wheels"])

    def test_merge_folds_one_theme_into_another(self):
        code, out, _ = self.run_cli(
            "themes", "merge", "Python wheels", "OpenEXR support"
        )
        self.assertEqual(code, 0)
        self.assertIn("Python wheels", out)
        self.assertEqual(self.docs_of("OpenEXR support"), ["pr#1", "pr#2"])
        self.assertEqual(self.names(), ["OpenEXR support"])

    def test_delete_removes_and_blocks_the_theme(self):
        code, out, _ = self.run_cli("themes", "delete", "Python wheels")
        self.assertEqual(code, 0)
        self.assertIn("Python wheels", out)
        self.assertEqual(self.names(), ["OpenEXR support"])
        self.assertTrue(Registry(self.conn).is_blocked("Python wheels"))

    def test_unknown_theme_is_an_error(self):
        for args in (
            ("rename", "Nope", "Other"),
            ("merge", "Nope", "OpenEXR support"),
            ("delete", "Nope"),
        ):
            with self.subTest(args):
                code, out, err = self.run_cli("themes", *args)
                self.assertEqual(code, 1)
                self.assertIn("error: no theme named 'Nope'", err)
                self.assertEqual(out, "")

    def test_reset_without_yes_only_reports(self):
        code, out, _ = self.run_cli("themes", "reset")
        self.assertEqual(code, 1)
        self.assertIn("2 themes", out)
        self.assertIn("--yes", out)
        self.assertEqual(len(self.names()), 2)

    def test_reset_with_yes_clears_themes_and_tags(self):
        code, out, _ = self.run_cli("themes", "reset", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("2 themes", out)
        self.assertEqual(self.names(), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM doc_themes").fetchone()[0], 0
        )


class TagTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.add_pr(self.conn, 1, "Add EXR tiles")

    def enable(self, host, extra=""):
        self.write_config(
            f'[ollama]\nhost = "{host}"\n[themes]\nenabled = true\n{extra}'
        )

    def saved_tags(self):
        return [
            tuple(r)
            for r in self.conn.execute(
                "SELECT d.doc_ref, t.name FROM doc_themes d JOIN themes t "
                "ON t.id = d.theme_id"
            )
        ]

    def test_refuses_without_documents(self):
        self.conn.execute("DELETE FROM items")
        self.conn.commit()
        self.enable("http://127.0.0.1:1")
        code, _, err = self.run_cli("tag")
        self.assertEqual(code, 1)
        self.assertIn("no documents yet; run fetch first", err)

    def test_tags_documents_and_reports(self):
        stub = StubOllama(self, EXR_REPLY)
        self.enable(stub.url)
        code, out, _ = self.run_cli("tag")
        self.assertEqual(code, 0)
        self.assertIn("[1/1] 2020-01-02 pr#1..pr#1: 1 with themes", out)
        self.assertIn("documents: 1 tagged, 0 unchanged, 0 skipped", out)
        self.assertIn("1 new themes, 0 aliases", out)
        self.assertEqual(self.saved_tags(), [("pr#1", "OpenEXR support")])
        self.assertEqual(stub.requests[0]["body"]["options"]["num_predict"], 4096)

    def test_rerun_skips_unchanged_documents_until_forced(self):
        self.enable(StubOllama(self, EXR_REPLY).url)
        self.run_cli("tag")
        _, out, _ = self.run_cli("tag")
        self.assertIn("documents: 0 tagged, 1 unchanged", out)
        _, out, _ = self.run_cli("tag", "--force")
        self.assertIn("documents: 1 tagged, 0 unchanged", out)

    def test_since_leaves_out_older_documents(self):
        self.enable(StubOllama(self, EXR_REPLY).url)
        _, out, _ = self.run_cli("tag", "--since", "2020-01-03")
        self.assertIn("documents: 0 tagged", out)
        _, out, _ = self.run_cli("tag", "--since", "2020-01-02")
        self.assertIn("documents: 1 tagged", out)

    def test_limit_caps_documents_per_run(self):
        self.add_pr(self.conn, 2, "Fix EXR header", created=TS + 1)
        self.enable(StubOllama(self, EXR_REPLY).url)
        _, out, _ = self.run_cli("tag", "--limit", "1")
        self.assertIn("documents: 1 tagged", out)

    def test_batch_docs_overrides_the_config(self):
        self.add_pr(self.conn, 2, "Fix EXR header", created=TS + 1)
        stub = StubOllama(self, EXR_REPLY)
        self.enable(stub.url)
        self.run_cli("tag", "--batch-docs", "1")
        self.assertEqual(len(stub.requests), 2)

    def test_bad_since_date_is_an_error(self):
        self.enable(StubOllama(self, EXR_REPLY).url)
        code, _, err = self.run_cli("tag", "--since", "yesterday")
        self.assertEqual(code, 1)
        self.assertIn("error: ", err)

    def test_unreachable_model_says_progress_is_saved(self):
        self.enable(f"http://127.0.0.1:{unused_port()}")
        code, _, err = self.run_cli("tag")
        self.assertEqual(code, 1)
        self.assertIn("cannot reach Ollama", err)
        self.assertIn("Progress so far is saved; rerun to continue.", err)

    def test_sample_is_a_dry_run_that_saves_nothing(self):
        self.conn.execute("INSERT INTO releases VALUES ('1.0', 'v1.0.0', ?)", (TS * 2,))
        self.conn.commit()
        stub = StubOllama(self, ['{"ok": 1}', EXR_REPLY])
        self.enable(stub.url)
        code, out, _ = self.run_cli("tag", "--sample", "1")
        self.assertEqual(code, 0)
        self.assertIn("loaded in", out)
        self.assertIn("== 1 documents, 8 per call (dry run)", out)
        self.assertIn("2020-01-02 pr#1", out)
        self.assertIn("-> OpenEXR support", out)
        self.assertIn("== themes created (1)\n  OpenEXR support: EXR files", out)
        self.assertEqual(self.saved_tags(), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0], 0
        )

    def test_sample_cuts_long_titles_and_reports_the_time(self):
        self.conn.execute("UPDATE items SET title = ?", ("x" * 70,))
        self.conn.execute("INSERT INTO releases VALUES ('1.0', 'v1.0.0', ?)", (TS * 2,))
        self.conn.commit()
        self.enable(StubOllama(self, ['{"ok": 1}', EXR_REPLY]).url)
        _, out, _ = self.run_cli("tag", "--sample", "1")
        self.assertIn("x" * 60 + "\n      -> OpenEXR support", out)
        self.assertNotIn("x" * 61, out)
        self.assertRegex(
            out,
            r"== time: \d+s for 1 documents \(\d+\.\d\ds each\), 0 skipped; "
            r"all 1 would take about \d+\.\dh",
        )

    def test_sample_needs_releases(self):
        self.enable(StubOllama(self, EXR_REPLY).url)
        code, _, err = self.run_cli("tag", "--sample", "1")
        self.assertEqual(code, 1)
        self.assertIn("no releases found", err)


class ExportTest(CliTestCase):
    def setUp(self):
        super().setUp()
        conn = self.connect()
        self.add_pr(conn, 1, "Add EXR tiles")
        add_commit(conn, "c1", TS, "Ann Lee", "ann@a.example")
        conn.commit()

    def test_writes_json_to_the_chosen_file(self):
        out_path = self.tmp / "out" / "x.json"
        code, out, _ = self.run_cli("export", "--out", str(out_path))
        self.assertEqual(code, 0)
        data = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertCountEqual(data["docs"]["source"], ["pr", "commit"])
        self.assertIn("people 2, documents 2, activity 2 (0 without a document)", out)
        self.assertIn("total", out)
        self.assertIn(f"-> {out_path}", out)

    def test_defaults_to_the_data_dir(self):
        self.run_cli("export")
        self.assertTrue((self.tmp / "data" / "org__proj.json").exists())


class PageTest(CliTestCase):
    def test_out_writes_one_page_and_skips_the_other_projects(self):
        out_path = self.tmp / "out" / "p.html"
        code, out, _ = self.run_cli("page", "--out", str(out_path))
        self.assertEqual(code, 0)
        self.assertTrue(out_path.exists())
        self.assertIn(f"page: {out_path} (", out)
        self.assertNotIn("rebuilt:", out)


class MainTest(CliTestCase):
    def test_invalid_config_is_an_error(self):
        self.path.write_text('[repo]\ngithub = "nope"\n')
        code, _, err = self.run_cli("people")
        self.assertEqual(code, 1)
        self.assertIn('error: [repo] github must be "owner/name"', err)

    def test_missing_config_is_an_error(self):
        self.path.unlink()
        code, _, err = self.run_cli("people")
        self.assertEqual(code, 1)
        self.assertIn("error: ", err)

    def test_command_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main([])


if __name__ == "__main__":
    unittest.main()
