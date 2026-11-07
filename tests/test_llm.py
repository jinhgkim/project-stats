"""Ollama client and cache tests, copied from ~/projects/metacognition
(tests/test_llm_config.py) along with projstats/llm.py."""

import contextlib
import io
import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from projstats import cli, config, storage
from projstats.llm import (
    CachedProvider,
    InvalidOutputError,
    LLMError,
    OllamaProvider,
)
from tests.fakes import FakeProvider


class StubOllama:
    """A real local HTTP server that answers /api/chat with a canned reply."""

    def __init__(self, test, content: str | list[str] = "", raw: bytes | None = None):
        """`content` may be a list: one reply per request, the last one repeating."""
        self.requests: list[dict] = []
        replies = content if isinstance(content, list) else [content]
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                stub.requests.append(
                    {"path": self.path, "body": json.loads(self.rfile.read(length))}
                )
                text = replies[min(len(stub.requests), len(replies)) - 1]
                reply = raw or json.dumps({"message": {"content": text}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        test.addCleanup(server.server_close)
        test.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_address[1]}/"


def unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OllamaProviderTest(unittest.TestCase):
    def test_sends_schema_and_parses_reply(self):
        stub = StubOllama(self, '{"ok": true}')
        provider = OllamaProvider(stub.url, "test-model")
        schema = {"type": "object"}
        self.assertEqual(provider.generate_json("t", "sys", "hi", schema), {"ok": True})

        [request] = stub.requests
        self.assertEqual(request["path"], "/api/chat")
        body = request["body"]
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["format"], schema)
        self.assertFalse(body["stream"])
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["messages"][1], {"role": "user", "content": "hi"})

    def test_name_reflects_settings_that_change_output(self):
        self.assertNotEqual(
            OllamaProvider("http://x", "m").name,
            OllamaProvider("http://x", "m", think=True).name,
        )
        self.assertNotEqual(
            OllamaProvider("http://x", "a").name, OllamaProvider("http://x", "b").name
        )

    def test_invalid_json_raises(self):
        provider = OllamaProvider(StubOllama(self, "nope").url, "test-model")
        with self.assertRaises(LLMError):
            provider.generate_json("t", "sys", "hi", {})

    def test_non_json_response_raises(self):
        stub = StubOllama(self, raw=b"<html>502 Bad Gateway</html>")
        provider = OllamaProvider(stub.url, "test-model")
        with self.assertRaises(LLMError):
            provider.generate_json("t", "sys", "hi", {})

    def test_retries_invalid_json_once_with_randomness(self):
        stub = StubOllama(
            self, ['{"messages": [{"id": "m1", "topics": ["a", "a", ', '{"ok": 1}']
        )
        provider = OllamaProvider(stub.url, "m")
        self.assertEqual(provider.generate_json("t", "s", "p", {}), {"ok": 1})
        temperatures = [r["body"]["options"]["temperature"] for r in stub.requests]
        self.assertEqual(temperatures[0], 0)
        self.assertGreater(temperatures[1], 0)

    def test_retry_turns_thinking_off(self):
        stub = StubOllama(self, ["", '{"ok": 1}'])
        provider = OllamaProvider(stub.url, "m", think=True)
        self.assertEqual(provider.generate_json("t", "s", "p", {}), {"ok": 1})
        self.assertEqual([r["body"]["think"] for r in stub.requests], [True, False])

    def test_invalid_twice_raises_invalid_output(self):
        stub = StubOllama(self, ["nope", "still nope"])
        with self.assertRaises(InvalidOutputError):
            OllamaProvider(stub.url, "m").generate_json("t", "s", "p", {})
        self.assertEqual(len(stub.requests), 2)

    def test_max_tokens_caps_output(self):
        stub = StubOllama(self, '{"ok": 1}')
        OllamaProvider(stub.url, "m", max_tokens=2048).generate_json("t", "s", "p", {})
        self.assertEqual(stub.requests[0]["body"]["options"]["num_predict"], 2048)

    def test_context_window_is_requested(self):
        stub = StubOllama(self, '{"ok": 1}')
        OllamaProvider(stub.url, "m", context=32768).generate_json("t", "s", "p", {})
        self.assertEqual(stub.requests[0]["body"]["options"]["num_ctx"], 32768)

    def test_unreachable_server_raises(self):
        provider = OllamaProvider(f"http://127.0.0.1:{unused_port()}", "m", timeout=5)
        with self.assertRaises(LLMError):
            provider.generate_json("t", "sys", "hi", {})


class CachedProviderTest(unittest.TestCase):
    def test_identical_requests_hit_cache(self):
        fake = FakeProvider(lambda task, prompt: {"echo": prompt})
        conn = storage.connect(":memory:")
        self.addCleanup(conn.close)
        llm = CachedProvider(fake, conn)
        self.assertEqual(llm.generate_json("t", "s", "a", {}), {"echo": "a"})
        self.assertEqual(llm.generate_json("t", "s", "a", {}), {"echo": "a"})
        self.assertEqual(llm.generate_json("t", "s", "b", {}), {"echo": "b"})
        self.assertEqual(len(fake.calls), 2)


class OllamaConfigTest(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        tmp.write('[repo]\ngithub = "o/r"\n' + text)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def test_defaults(self):
        cfg = config.load(self.write(""))
        self.assertEqual(cfg.ollama.model, "ornith-1.5:9b")
        self.assertFalse(cfg.ollama.think)

    def test_reads_values(self):
        cfg = config.load(self.write('[ollama]\nmodel = "m"\nthink = true\n'))
        self.assertEqual((cfg.ollama.model, cfg.ollama.think), ("m", True))
        self.assertEqual(cfg.ollama.host, "http://localhost:11434")

    def test_unknown_setting_is_an_error(self):
        with self.assertRaises(ValueError):
            config.load(self.write("[ollama]\nmodle = 'typo'\n"))


class ThemesSwitchTest(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        tmp.write('[repo]\ngithub = "o/r"\n' + text)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def test_on_by_default(self):
        self.assertTrue(config.load(self.write("")).themes.enabled)

    def test_can_be_turned_off(self):
        cfg = config.load(self.write("[themes]\nenabled = false\n"))
        self.assertFalse(cfg.themes.enabled)

    def test_must_be_true_or_false(self):
        with self.assertRaises(ValueError):
            config.load(self.write('[themes]\nenabled = "no"\n'))

    def test_tag_refuses_when_off(self):
        path = self.write("[themes]\nenabled = false\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["tag", path]), 1)
        self.assertIn("themes are off", err.getvalue())


if __name__ == "__main__":
    unittest.main()
