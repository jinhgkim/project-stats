import re
import unittest
from datetime import UTC, datetime

from projstats import storage, themes
from projstats.config import ThemesConfig
from projstats.documents import Document, release_periods
from projstats.llm import InvalidOutputError
from projstats.releases import Release
from projstats.tagger import (
    batches,
    build_prompt,
    is_catch_all,
    memory_copy,
    parse,
    sample,
    tag_documents,
)
from tests.fakes import FakeProvider

KEYWORDS = {
    r"\bexr\b": "OpenEXR support",
    r"\bspan\b": "Span-based APIs",
    r"\bfuzz": "Fuzzing and hardening",
    r"\bwheel": "Python wheels",
}


def ts(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


def doc(ref, year, title, source="pr", month=1):
    return Document(source, ref, ts(year, month), title, "")


def items(prompt: str) -> dict[str, str]:
    """{local id: text} from a tag prompt."""
    body = prompt.split("Items:", 1)[1]
    parts = re.split(r"^\[(d\d+)\] [^\n]*\n", body, flags=re.M)
    return dict(zip(parts[1::2], (p.strip() for p in parts[2::2]), strict=True))


class FakeTagger(FakeProvider):
    """Tags by keyword; `extra` adds fixed themes; `fail` breaks matching batches."""

    def __init__(self, extra=(), fail=lambda prompt: False):
        def handler(task, prompt):
            if task == "merge":
                return {"matches": []}
            if fail(prompt):
                raise InvalidOutputError("tag: model returned invalid JSON")
            return {
                "documents": [
                    {
                        "id": local_id,
                        "themes": [
                            name
                            for pattern, name in KEYWORDS.items()
                            if re.search(pattern, text, re.I)
                        ]
                        + list(extra),
                    }
                    for local_id, text in items(prompt).items()
                ],
                "new_themes": [],
            }

        super().__init__(handler)

    def tag_prompts(self):
        return [prompt for task, prompt in self.calls if task == "tag"]


DOCS = [
    doc("pr#3", 2022, "Add span overloads"),
    doc("pr#1", 2020, "fix(exr): handle tiles"),
    doc("issue#2", 2021, "Crash found by fuzzing", source="issue"),
    doc("abc1234567", 2023, "Fix typo", source="commit"),
]


class TaggerTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.cfg = ThemesConfig(about="An image library.", batch_docs=2)

    def run_tagger(self, llm, docs=DOCS, texts=None, **kw):
        texts = texts or [d.title for d in docs]
        return tag_documents(self.conn, llm, docs, texts, self.cfg, **kw)

    def tags(self, conn=None):
        rows = (conn or self.conn).execute(
            "SELECT d.doc_ref, t.name FROM doc_themes d JOIN themes t "
            "ON t.id = d.theme_id ORDER BY d.doc_ref, t.name"
        )
        return [tuple(r) for r in rows]


class TagDocumentsTest(TaggerTestCase):
    def test_tags_oldest_first_and_saves_themes(self):
        llm = FakeTagger()
        stats = self.run_tagger(llm)
        self.assertEqual((stats.tagged, stats.batches, stats.failed), (4, 2, 0))
        self.assertEqual(
            self.tags(),
            [
                ("issue#2", "Fuzzing and hardening"),
                ("pr#1", "OpenEXR support"),
                ("pr#3", "Span-based APIs"),
            ],
        )
        first, second = llm.tag_prompts()
        self.assertEqual(
            list(items(first).values()),
            ["fix(exr): handle tiles", "Crash found by fuzzing"],
        )
        self.assertIn("Commit, 2023-01-01", second)

    def test_existing_themes_are_listed_in_later_prompts(self):
        llm = FakeTagger()
        self.run_tagger(llm)
        first, second = llm.tag_prompts()
        self.assertIn("(none yet)", first)
        self.assertIn("- Fuzzing and hardening", second)
        self.assertIn("- OpenEXR support", second)

    def test_project_description_is_in_the_system_prompt(self):
        seen = []

        class Recording(FakeTagger):
            def generate_json(self, task, system, prompt, schema):
                seen.append(system)
                return super().generate_json(task, system, prompt, schema)

        self.run_tagger(Recording())
        self.assertIn("About the project: An image library.", seen[0])
        self.assertNotIn("Main areas", seen[0])

        seen.clear()
        self.cfg.areas = "formats, tools"
        self.cfg.project_names = ["Imglib"]
        self.run_tagger(Recording(), force=True)
        self.assertIn("Main areas: formats, tools\n", seen[0])
        self.assertIn('"Imglib support"', seen[0])

    def test_existing_themes_are_listed_with_descriptions(self):
        class Describing(FakeTagger):
            def generate_json(self, task, system, prompt, schema):
                result = super().generate_json(task, system, prompt, schema)
                if task == "tag":
                    result["new_themes"] = [
                        {"name": "OpenEXR support", "description": "EXR files"}
                    ]
                return result

        llm = Describing()
        self.run_tagger(llm)
        self.assertIn("- OpenEXR support: EXR files", llm.tag_prompts()[1])

    def test_project_catch_alls_dropped(self):
        self.cfg.project_names = ["OpenImageIO", "OIIO"]
        llm = FakeTagger(extra=["OpenImageIO support", "OIIO core library"])
        self.run_tagger(llm, docs=[DOCS[1]])
        self.assertEqual([name for _, name in self.tags()], ["OpenEXR support"])

    def test_rerun_only_tags_new_or_changed_documents(self):
        self.run_tagger(FakeTagger())
        llm = FakeTagger()
        stats = self.run_tagger(llm)
        self.assertEqual((stats.tagged, stats.unchanged), (0, 4))
        self.assertEqual(llm.calls, [])

        texts = [d.title for d in DOCS]
        texts[0] = "Add span overloads for python wheels"
        stats = self.run_tagger(FakeTagger(), texts=texts)
        self.assertEqual((stats.tagged, stats.unchanged), (1, 3))
        self.assertIn(("pr#3", "Python wheels"), self.tags())

        stats = self.run_tagger(FakeTagger(), texts=texts, force=True)
        self.assertEqual(stats.tagged, 4)

    def test_failed_batch_is_retried_next_run(self):
        stats = self.run_tagger(FakeTagger(fail=lambda p: "span" in p))
        self.assertEqual((stats.tagged, stats.failed), (2, 2))
        stats = self.run_tagger(FakeTagger())
        self.assertEqual((stats.tagged, stats.unchanged), (2, 2))
        self.assertIn(("pr#3", "Span-based APIs"), self.tags())

    def test_since_skips_older_documents(self):
        stats = self.run_tagger(FakeTagger(), since=ts(2022))
        self.assertEqual((stats.tagged, stats.unchanged), (2, 0))
        tagged = {r[0] for r in self.conn.execute("SELECT doc_ref FROM doc_tagging")}
        self.assertEqual(tagged, {"pr#3", "abc1234567"})

    def test_limit(self):
        stats = self.run_tagger(FakeTagger(), limit=3)
        self.assertEqual(stats.tagged, 3)
        tagged = {r[0] for r in self.conn.execute("SELECT doc_ref FROM doc_tagging")}
        self.assertEqual(tagged, {"pr#1", "issue#2", "pr#3"})  # the 3 oldest

    def test_generic_themes_dropped_and_count_capped(self):
        llm = FakeTagger(extra=["Bug fixes", "Refactoring", "Docs", "Tests", "CI"])
        self.run_tagger(llm, docs=[DOCS[1]])
        self.assertEqual(
            [name for _, name in self.tags()],
            ["Docs", "OpenEXR support", "Tests"],
        )

    def test_deleted_theme_is_not_assigned_again(self):
        self.run_tagger(FakeTagger())
        themes.delete(self.conn, "OpenEXR support")
        self.run_tagger(FakeTagger(), force=True)
        self.assertNotIn("OpenEXR support", [name for _, name in self.tags()])

    def test_dry_run_copy_leaves_the_database_unchanged(self):
        copy = memory_copy(self.conn)
        self.addCleanup(copy.close)
        texts = [d.title for d in DOCS]
        tag_documents(copy, FakeTagger(), DOCS, texts, self.cfg)
        self.assertEqual(len(self.tags(copy)), 3)
        self.assertEqual(self.tags(), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM doc_tagging").fetchone()[0], 0
        )


class PieceTest(unittest.TestCase):
    def test_batches_by_count_and_chars(self):
        pairs = [
            (doc(f"d{i}", 2020, ""), "x" * n) for i, n in enumerate([3, 3, 3, 9, 1])
        ]
        sizes = [len(b) for b in batches(pairs, max_docs=2, max_chars=8)]
        # [3, 3] hits the count; [3] then 9 would pass 8 chars; [9] alone; [1].
        self.assertEqual(sizes, [2, 1, 1, 1])

    def test_build_prompt(self):
        prompt, local_ids = build_prompt(
            [(DOCS[1], "fix(exr): handle tiles")], ["OpenEXR support"]
        )
        self.assertEqual(local_ids, {"d1": "pr#1"})
        self.assertIn("- OpenEXR support", prompt)
        self.assertIn("[d1] PR, 2020-01-01\nfix(exr): handle tiles", prompt)

    def test_parse_ignores_unknown_ids_and_bad_items(self):
        result = {
            "documents": [
                {"id": "d1", "themes": ["OpenEXR support", "openexr SUPPORT", ""]},
                {"id": "d9", "themes": ["Unknown doc"]},
                "not a dict",
                {"id": "[d2]", "themes": "not a list"},
            ],
            "new_themes": [{"name": "OpenEXR support", "description": "EXR files"}],
        }
        tags, descriptions = parse(result, {"d1": "pr#1", "d2": "pr#2"}, 3)
        self.assertEqual(tags, {"pr#1": ["OpenEXR support"]})
        self.assertEqual(descriptions, {"openexr support": "EXR files"})

    def test_is_catch_all(self):
        names = ["OpenImageIO", "OIIO"]
        for name in ["OpenImageIO", "OIIO core", "OpenImageIO Support", "oiio API"]:
            self.assertTrue(is_catch_all(name, names), name)
        for name in ["OIIO Python bindings", "OpenEXR support", "Build system"]:
            self.assertFalse(is_catch_all(name, names), name)
        self.assertFalse(is_catch_all("OIIO core", []))

    def test_sample_spreads_across_release_cycles(self):
        periods = release_periods(
            [Release("1.0", "a", ts(2020)), Release("1.1", "b", ts(2022))]
        )
        docs = [doc(f"a{i}", 2019, "", month=1 + i % 12) for i in range(20)]
        docs += [doc(f"b{i}", 2021, "", month=1 + i % 12) for i in range(20)]
        docs += [doc(f"c{i}", 2023, "", month=1 + i % 12) for i in range(2)]
        picked = sample(docs, periods, 6)
        self.assertEqual([p.ref[0] for p in picked], ["a", "a", "b", "b", "c", "c"])
        self.assertEqual(picked, sorted(picked, key=lambda d: d.ts))


if __name__ == "__main__":
    unittest.main()
