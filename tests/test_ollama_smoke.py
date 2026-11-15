"""Smoke tests against a real Ollama, skipped unless PROJSTATS_OLLAMA_SMOKE=1.

    PROJSTATS_OLLAMA_SMOKE=1 python -m unittest tests.test_ollama_smoke

PROJSTATS_OLLAMA_HOST and PROJSTATS_OLLAMA_MODEL override the defaults in
OllamaConfig. These check structure only: the model's wording differs between
runs and hardware, so no theme name is asserted.
"""

import os
import unittest

from projstats import storage
from projstats.config import OllamaConfig, ThemesConfig
from projstats.documents import Document
from projstats.llm import OllamaProvider
from projstats.tagger import tag_documents
from projstats.themes import Registry, resolve

DEFAULTS = OllamaConfig()
DOCS = [
    ("pr#1", "Read OpenEXR tiled images faster", "Speeds up reading tiles."),
    ("pr#2", "Add a wheel build for Python 3.13", "Publishes wheels from CI."),
    ("issue#3", "Crash when fuzzing the TIFF reader", "A fuzzer found a crash."),
]


@unittest.skipUnless(
    os.environ.get("PROJSTATS_OLLAMA_SMOKE") == "1",
    "set PROJSTATS_OLLAMA_SMOKE=1 to run against a real Ollama",
)
class OllamaSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = OllamaProvider(
            os.environ.get("PROJSTATS_OLLAMA_HOST", DEFAULTS.host),
            os.environ.get("PROJSTATS_OLLAMA_MODEL", DEFAULTS.model),
            DEFAULTS.timeout,
            DEFAULTS.think,
            4096,
            context=DEFAULTS.context,
        )
        # Loads the model once, so each test measures a warm call.
        cls.provider.generate_json(
            "warmup", "Reply in JSON.", "Say ok.", {"type": "object"}
        )

    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_reply_follows_a_small_schema(self):
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        result = self.provider.generate_json(
            "smoke", "Reply in JSON.", "Answer with the word yes.", schema
        )
        self.assertIsInstance(result.get("answer"), str)

    def test_tagging_real_documents_gives_usable_output(self):
        docs = [
            Document("pr", ref, i, title, body)
            for i, (ref, title, body) in enumerate(DOCS)
        ]
        texts = [f"{d.title}\n{d.body}" for d in docs]
        cfg = ThemesConfig(about="An image library.", batch_docs=len(docs))
        stats = tag_documents(self.conn, self.provider, docs, texts, cfg)
        self.assertEqual((stats.failed, stats.tagged), (0, len(docs)))
        self.assertGreaterEqual(stats.themes_created, 1)
        names = [r[0] for r in self.conn.execute("SELECT name FROM themes")]
        self.assertTrue(all(n.strip() for n in names))
        tagged = self.conn.execute("SELECT COUNT(*) FROM doc_tagging").fetchone()[0]
        self.assertEqual(tagged, len(docs))

    def test_merge_step_places_a_name_on_a_theme(self):
        registry = Registry(self.conn)
        registry.create("OpenColorIO")
        ids = resolve(registry, self.provider, {"OCIO"}, {})
        self.assertEqual(set(ids), {"OCIO"})
        self.assertIn(ids["OCIO"], Registry(self.conn).names)


if __name__ == "__main__":
    unittest.main()
