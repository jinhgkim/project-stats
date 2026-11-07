"""LLM access: a local Ollama client plus a SQLite-backed response cache.

Copied from ~/projects/metacognition (metacognition/llm.py); keep fixes in sync.
"""

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(Exception):
    pass


class InvalidOutputError(LLMError):
    """The model answered, but not with usable JSON; other items may still work."""


class Provider(Protocol):
    name: str

    def generate_json(self, task: str, system: str, prompt: str, schema: dict) -> dict:
        """Return the model's reply parsed as JSON matching `schema`."""
        ...


class OllamaProvider:
    def __init__(
        self,
        host: str,
        model: str,
        timeout: float = 600,
        think: bool = False,
        max_tokens: int | None = None,
        context: int | None = None,
    ):
        self.url = host.rstrip("/") + "/api/chat"
        self.model = model
        self.timeout = timeout
        self.think = think
        self.max_tokens = max_tokens
        self.context = context
        # The name keys the cache, so it must change whenever output could.
        self.name = f"ollama:{model}" + (":think" if think else "")

    def generate_json(self, task: str, system: str, prompt: str, schema: dict) -> dict:
        try:
            return self._call(task, system, prompt, schema, 0, self.think)
        except InvalidOutputError:
            # The model sometimes loops, in its answer or in its thinking (using
            # up the whole token budget). Retry with a little randomness, and
            # without thinking.
            return self._call(task, system, prompt, schema, 0.7, think=False)

    def _call(
        self,
        task: str,
        system: str,
        prompt: str,
        schema: dict,
        temperature: float,
        think: bool,
    ) -> dict:
        options = {"temperature": temperature, "seed": 0}
        if self.max_tokens:
            options["num_predict"] = self.max_tokens
        if self.context:
            # Ollama's default window (4096 tokens) is too small for our prompts.
            options["num_ctx"] = self.context
        body = {
            "model": self.model,
            "stream": False,
            "think": think,
            "format": schema,
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise LLMError(f"{task}: Ollama returned {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"{task}: cannot reach Ollama at {self.url}: {e}") from e
        except json.JSONDecodeError as e:
            raise LLMError(f"{task}: Ollama returned a non-JSON response") from e

        content = (payload.get("message") or {}).get("content", "")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            raise InvalidOutputError(f"{task}: model returned invalid JSON") from e
        if not isinstance(result, dict):
            raise InvalidOutputError(f"{task}: expected a JSON object")
        return result


class CachedProvider:
    """Wraps a provider so identical requests are answered from SQLite."""

    def __init__(self, provider: Provider, conn: sqlite3.Connection):
        self.provider = provider
        self.conn = conn
        self.name = provider.name

    def generate_json(self, task: str, system: str, prompt: str, schema: dict) -> dict:
        key = hashlib.sha256(
            json.dumps(
                [self.name, task, system, prompt, schema], sort_keys=True
            ).encode()
        ).hexdigest()
        row = self.conn.execute(
            "SELECT response FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is not None:
            return json.loads(row["response"])
        result = self.provider.generate_json(task, system, prompt, schema)
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, response, created_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(result), time.time()),
            )
        return result
