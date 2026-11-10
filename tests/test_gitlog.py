"""Git import against a tiny repository built in a temp dir.

History (oldest first), plus a merge that must be skipped:
  c1  Alice <alice@old.example>   adds .mailmap; body has two paragraphs
  c2  Bob <bob@main.example>      Co-authored-by: Alice <alice@old.example>
  c3  Bob <bob@main.example>      on a side branch
  m   merge of the side branch (--no-ff)
.mailmap maps alice@old.example to "Alice Smith <alice@new.example>".
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from projstats import gitlog, storage
from tests import isolate_git

MAILMAP = "Alice Smith <alice@new.example> <alice@old.example>\n"


class GitRepo:
    def __init__(self, path: Path):
        self.path = path
        self.clock = 1_577_836_800  # 2020-01-01 UTC
        path.mkdir()
        self.run("init", "-q", "-b", "main")

    def run(self, *args: str, author=("Bob", "bob@main.example")) -> str:
        self.clock += 86_400
        env = {
            "GIT_AUTHOR_NAME": author[0],
            "GIT_AUTHOR_EMAIL": author[1],
            "GIT_COMMITTER_NAME": author[0],
            "GIT_COMMITTER_EMAIL": author[1],
            "GIT_AUTHOR_DATE": f"@{self.clock} +0000",
            "GIT_COMMITTER_DATE": f"@{self.clock} +0000",
        }
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self, message: str, files: dict[str, str] | None = None, **kw) -> str:
        for name, text in (files or {"log.txt": message}).items():
            p = self.path / name
            p.write_text(p.read_text() + text if p.exists() else text)
            self.run("add", name)
        self.run("commit", "-q", "-m", message, **kw)
        return self.run("rev-parse", "HEAD")


class GitImportTest(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        self.work = GitRepo(root / "work")
        alice = ("Alice", "alice@old.example")
        self.c1 = self.work.commit(
            "first\n\nline one\n\nline two",
            {".mailmap": MAILMAP, "a.txt": "a"},
            author=alice,
        )
        self.c2 = self.work.commit(
            "second\n\nCo-authored-by: Alice <alice@old.example>"
        )
        self.work.run("checkout", "-q", "-b", "side")
        self.c3 = self.work.commit("side work", {"b.txt": "b"})
        self.work.run("checkout", "-q", "main")
        self.work.run("merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.merge = self.work.run("rev-parse", "HEAD")

        self.bare = root / "mirror.git"
        self.assertEqual(
            gitlog.sync_clone(str(self.work.path), self.bare, blobless=False), "cloned"
        )
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def sync(self) -> gitlog.ImportStats:
        self.assertEqual(
            gitlog.sync_clone(str(self.work.path), self.bare, blobless=False),
            "updated",
        )
        return gitlog.import_commits(self.conn, self.bare)

    def commit_row(self, sha):
        return self.conn.execute(
            "SELECT * FROM commits WHERE sha = ?", (sha,)
        ).fetchone()

    def test_imports_non_merge_commits(self):
        stats = gitlog.import_commits(self.conn, self.bare)
        expected = gitlog.git(self.bare, "rev-list", "--no-merges", "--count", "HEAD")
        self.assertEqual(stats.total, int(expected.stdout))
        self.assertEqual((stats.new, stats.total), (3, 3))
        self.assertFalse(stats.rewritten)
        self.assertIsNone(self.commit_row(self.merge))

    def test_mailmap_applied_and_raw_kept(self):
        gitlog.import_commits(self.conn, self.bare)
        row = self.commit_row(self.c1)
        self.assertEqual(
            (row["author_name"], row["author_email"]),
            ("Alice Smith", "alice@new.example"),
        )
        self.assertEqual(
            (row["raw_name"], row["raw_email"]), ("Alice", "alice@old.example")
        )

    def test_missing_email_gets_a_stand_in_per_name(self):
        shas = [self.work.commit(n, author=(n, "")) for n in ("cvsone", "cvstwo")]
        self.sync()
        self.assertEqual(
            [self.commit_row(sha)["author_email"] for sha in shas],
            ["cvsone@no-email.invalid", "cvstwo@no-email.invalid"],
        )
        self.assertEqual(self.commit_row(shas[0])["raw_email"], "")

    def test_body_kept_intact(self):
        gitlog.import_commits(self.conn, self.bare)
        row = self.commit_row(self.c1)
        self.assertEqual(row["subject"], "first")
        self.assertEqual(row["body"], "line one\n\nline two")

    def test_coauthor_trailer_mapped(self):
        gitlog.import_commits(self.conn, self.bare)
        rows = self.conn.execute("SELECT * FROM commit_coauthors").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sha"], self.c2)
        self.assertEqual(
            (rows[0]["name"], rows[0]["email"]), ("Alice Smith", "alice@new.example")
        )
        self.assertEqual(rows[0]["raw_email"], "alice@old.example")

    def test_rerun_imports_only_new_commits(self):
        gitlog.import_commits(self.conn, self.bare)
        self.assertEqual(self.sync().new, 0)
        self.work.commit("fourth")
        stats = self.sync()
        self.assertEqual((stats.new, stats.total), (1, 4))
        self.assertFalse(stats.rewritten or stats.remapped)

    def test_rewritten_history_reimports(self):
        gitlog.import_commits(self.conn, self.bare)
        self.work.run("reset", "-q", "--hard", self.c2)
        replacement = self.work.commit("replacement")
        stats = self.sync()
        self.assertTrue(stats.rewritten)
        self.assertEqual((stats.new, stats.total), (3, 3))
        self.assertIsNone(self.commit_row(self.c3))
        self.assertIsNotNone(self.commit_row(replacement))

    def test_mailmap_change_remaps_stored_commits(self):
        gitlog.import_commits(self.conn, self.bare)
        self.work.commit(
            "update mailmap",
            {".mailmap": "Alice S. <alice@newest.example> <alice@old.example>\n"},
        )
        stats = self.sync()
        self.assertTrue(stats.remapped)
        row = self.commit_row(self.c1)
        self.assertEqual(
            (row["author_name"], row["author_email"]),
            ("Alice S.", "alice@newest.example"),
        )
        co = self.conn.execute("SELECT name, email FROM commit_coauthors").fetchone()
        self.assertEqual(tuple(co), ("Alice S.", "alice@newest.example"))


if __name__ == "__main__":
    unittest.main()
