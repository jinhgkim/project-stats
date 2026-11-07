"""Theme registry and fix-up commands, adapted from metacognition's tests."""

import json
import re
import unittest

from projstats import storage, themes
from projstats.themes import Registry, resolve, theme_key
from tests.fakes import FakeProvider


def merge_handler(synonyms: dict[str, str]):
    """Answers "merge" tasks: a candidate matches its synonym if it is listed."""

    def handler(task, prompt):
        assert task == "merge", task
        listed = set(re.findall(r"^- (.+)$", prompt, re.M))
        candidates = re.findall(r"^- (.+)$", prompt.split("Candidates:", 1)[1], re.M)
        return {
            "matches": [
                {
                    "candidate": c,
                    "same_as": synonyms[c] if synonyms.get(c) in listed else "",
                }
                for c in candidates
            ]
        }

    return handler


class ThemesTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def llm(self, **synonyms):
        return FakeProvider(merge_handler(synonyms))

    def tag(self, theme_id, *refs):
        with self.conn:
            self.conn.executemany(
                "INSERT INTO doc_themes (doc_ref, theme_id) VALUES (?, ?)",
                [(r, theme_id) for r in refs],
            )

    def theme(self, name):
        return self.conn.execute(
            "SELECT * FROM themes WHERE name = ?", (name,)
        ).fetchone()

    def docs(self, name):
        theme_id = Registry(self.conn).lookup(name)
        return sorted(
            r[0]
            for r in self.conn.execute(
                "SELECT doc_ref FROM doc_themes WHERE theme_id = ?", (theme_id,)
            )
        )


class ThemeKeyTest(unittest.TestCase):
    def test_ignores_case_punctuation_and_accents(self):
        cases = {
            "OpenEXR Support": "openexr support",
            "  openexr-support!": "openexr support",
            "OpenEXR_support": "openexr support",
            "C++ API": "c++ api",
            "C# bindings": "c# bindings",
            "Café Résumé": "cafe resume",
            "Straße": "strasse",
        }
        for name, key in cases.items():
            self.assertEqual(theme_key(name), key, name)


class ResolveTest(ThemesTestCase):
    def test_case_and_punctuation_variants_resolve_without_llm(self):
        registry = Registry(self.conn)
        span = registry.create("Span APIs")
        llm = self.llm()
        ids = resolve(registry, llm, {"span apis", "SPAN-APIs"}, {})
        self.assertEqual(set(ids.values()), {span})
        self.assertEqual(llm.calls, [])

    def test_new_names_create_themes_with_descriptions(self):
        registry = Registry(self.conn)
        resolve(
            registry,
            self.llm(),
            {"Fuzzing", "Python wheels"},
            {"fuzzing": "Fuzz testing of image readers"},
        )
        self.assertEqual(
            self.theme("Fuzzing")["description"], "Fuzz testing of image readers"
        )
        self.assertEqual(registry.created, 2)

    def test_llm_maps_a_synonym_onto_an_existing_theme(self):
        registry = Registry(self.conn)
        ocio = registry.create("OpenColorIO")
        ids = resolve(registry, self.llm(OCIO="OpenColorIO"), {"OCIO"}, {})
        self.assertEqual(ids["OCIO"], ocio)
        self.assertEqual(json.loads(self.theme("OpenColorIO")["aliases"]), ["OCIO"])
        self.assertEqual(registry.aliased, 1)

    def test_merge_between_new_candidates(self):
        registry = Registry(self.conn)
        llm = self.llm(**{"Span APIs": "Span-based APIs"})
        ids = resolve(registry, llm, {"Span APIs", "Span-based APIs"}, {})
        self.assertEqual(ids["Span APIs"], ids["Span-based APIs"])
        self.assertEqual(len(registry), 1)

    def test_merge_cycle_still_creates_one_theme(self):
        registry = Registry(self.conn)
        llm = self.llm(Alpha="Beta", Beta="Alpha")
        ids = resolve(registry, llm, {"Alpha", "Beta"}, {})
        self.assertEqual(ids["Alpha"], ids["Beta"])
        self.assertEqual(len(registry), 1)

    def test_reload_keeps_ids_and_aliases(self):
        registry = Registry(self.conn)
        ids = resolve(registry, self.llm(OCIO="OpenColorIO"), {"OpenColorIO"}, {})
        resolve(registry, self.llm(OCIO="OpenColorIO"), {"OCIO"}, {})
        reloaded = Registry(self.conn)
        self.assertEqual(reloaded.lookup("ocio"), ids["OpenColorIO"])

    def test_prompt_lines_most_used_first_with_aliases(self):
        registry = Registry(self.conn)
        a = registry.create("Fuzzing")
        b = registry.create("OpenColorIO")
        registry.add_alias(b, "OCIO")
        self.tag(b, "pr#1", "pr#2")
        self.tag(a, "pr#3")
        self.assertEqual(
            registry.prompt_lines(10), ["OpenColorIO (also: OCIO)", "Fuzzing"]
        )
        self.assertEqual(registry.prompt_lines(1), ["OpenColorIO (also: OCIO)"])

    def test_prompt_lines_with_descriptions(self):
        Registry(self.conn).create("Fuzzing", "Handling malformed input")
        registry = Registry(self.conn)
        b = registry.create("OpenColorIO")
        registry.add_alias(b, "OCIO")
        self.assertEqual(
            registry.prompt_lines(10, descriptions=True),
            ["Fuzzing: Handling malformed input", "OpenColorIO (also: OCIO)"],
        )


class RenameTest(ThemesTestCase):
    def test_keeps_id_and_old_name_as_alias(self):
        theme_id = Registry(self.conn).create("Span APIs")
        themes.rename(self.conn, "Span APIs", "Span-based APIs")
        row = self.theme("Span-based APIs")
        self.assertEqual(row["id"], theme_id)
        self.assertEqual(json.loads(row["aliases"]), ["Span APIs"])

    def test_case_only_rename_adds_no_alias(self):
        Registry(self.conn).create("span apis")
        themes.rename(self.conn, "span apis", "Span APIs")
        self.assertEqual(json.loads(self.theme("Span APIs")["aliases"]), [])

    def test_onto_an_existing_theme_is_refused(self):
        registry = Registry(self.conn)
        registry.create("Fuzzing")
        registry.create("Hardening")
        with self.assertRaisesRegex(ValueError, "use merge"):
            themes.rename(self.conn, "Fuzzing", "Hardening")

    def test_onto_a_deleted_name_or_alias_is_refused(self):
        registry = Registry(self.conn)
        gone = registry.create("Travis CI")
        registry.add_alias(gone, "TravisCI")
        registry.create("CI")
        themes.delete(self.conn, "Travis CI")
        for name in ("Travis CI", "travisci"):
            with self.assertRaisesRegex(ValueError, "deleted"):
                themes.rename(self.conn, "CI", name)


class MergeTest(ThemesTestCase):
    def test_moves_documents_without_double_counting(self):
        registry = Registry(self.conn)
        narrow = registry.create("Deep image reading")
        broad = registry.create("Deep images")
        self.tag(narrow, "pr#1", "pr#2")
        self.tag(broad, "pr#2", "pr#3")
        themes.merge(self.conn, "Deep image reading", "Deep images")
        self.assertEqual(self.docs("Deep images"), ["pr#1", "pr#2", "pr#3"])
        self.assertTrue(themes.is_retired(self.conn, narrow))
        self.assertEqual(Registry(self.conn).lookup("Deep image reading"), broad)

    def test_carries_aliases(self):
        registry = Registry(self.conn)
        src = registry.create("OCIO configs")
        registry.add_alias(src, "OCIO config files")
        registry.create("OpenColorIO")
        themes.merge(self.conn, "OCIO configs", "OpenColorIO")
        self.assertEqual(
            json.loads(self.theme("OpenColorIO")["aliases"]),
            ["OCIO configs", "OCIO config files"],
        )

    def test_same_theme_is_refused(self):
        registry = Registry(self.conn)
        theme_id = registry.create("OpenColorIO")
        registry.add_alias(theme_id, "OCIO")
        with self.assertRaisesRegex(ValueError, "same theme"):
            themes.merge(self.conn, "OCIO", "OpenColorIO")


class DeleteTest(ThemesTestCase):
    def test_removes_tags_and_blocks_name_and_aliases(self):
        registry = Registry(self.conn)
        theme_id = registry.create("Bug fixes")
        registry.add_alias(theme_id, "Bugfixes")
        self.tag(theme_id, "pr#1")
        themes.delete(self.conn, "Bug fixes")
        self.assertEqual(self.docs("Bug fixes"), [])
        reloaded = Registry(self.conn)
        self.assertTrue(reloaded.is_blocked("bug fixes"))
        self.assertTrue(reloaded.is_blocked("BugFixes"))
        self.assertIsNone(reloaded.lookup("Bug fixes"))
        self.assertTrue(themes.is_retired(self.conn, theme_id))

    def test_unknown_theme(self):
        with self.assertRaisesRegex(ValueError, "no theme named"):
            themes.delete(self.conn, "Nope")


class ResetTest(ThemesTestCase):
    def test_clears_themes_and_tags_but_keeps_blocklist(self):
        registry = Registry(self.conn)
        a, b = registry.create("Fuzzing"), registry.create("Fuzz testing")
        self.tag(a, "pr#1", "pr#2")
        themes.merge(self.conn, "Fuzz testing", "Fuzzing")
        themes.delete(self.conn, "Fuzzing")
        self.assertTrue(themes.is_retired(self.conn, b))
        with self.conn:
            self.conn.execute(
                "INSERT INTO doc_tagging VALUES ('pr#1', 'h', 0), ('pr#2', 'h', 0)"
            )
        self.tag(registry.create("Build system"), "pr#3")

        counts = themes.reset(self.conn)
        self.assertEqual((counts.themes, counts.tags, counts.tagged_docs), (3, 1, 2))
        self.assertEqual(themes.reset_counts(self.conn), themes.ResetCounts(0, 0, 0))
        reloaded = Registry(self.conn)
        self.assertEqual(len(reloaded), 0)
        self.assertTrue(reloaded.is_blocked("Fuzzing"))
        self.assertTrue(reloaded.is_blocked("Fuzz testing"))


class SummaryTest(ThemesTestCase):
    def test_counts_and_date_range(self):
        registry = Registry(self.conn)
        a = registry.create("Fuzzing")
        registry.create("Unused")
        self.tag(a, "pr#1", "pr#2", "gone")
        rows = themes.summary(self.conn, {"pr#1": 100, "pr#2": 300})
        self.assertEqual(
            [(r.name, r.docs, r.first, r.last) for r in rows],
            [("Fuzzing", 3, 100, 300), ("Unused", 0, None, None)],
        )

    def test_empty_registry(self):
        self.assertEqual(themes.summary(self.conn, {}), [])


if __name__ == "__main__":
    unittest.main()
