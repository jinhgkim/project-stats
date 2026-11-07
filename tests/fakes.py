"""Stand-in for the LLM in tests: replies come from a handler function."""


class FakeProvider:
    def __init__(self, handler, name="fake"):
        self.handler = handler  # (task, prompt) -> dict
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, task, system, prompt, schema):
        self.calls.append((task, prompt))
        return self.handler(task, prompt)
