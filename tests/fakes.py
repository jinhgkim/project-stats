"""Stand-in for the LLM in tests: replies come from a handler function."""


class FakeProvider:
    def __init__(self, handler, name="fake"):
        self.handler = handler  # (task, prompt) -> dict
        self.name = name
        self.calls: list[tuple[str, str]] = []
        self.schemas: list[dict] = []

    def generate_json(self, task, system, prompt, schema):
        self.calls.append((task, prompt))
        self.schemas.append(schema)
        return self.handler(task, prompt)
