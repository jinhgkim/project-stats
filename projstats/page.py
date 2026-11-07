"""Write the self-contained web page: template + embedded data + page scripts.

The page's code lives in projstats/page/ as small files: core.js first, then
metrics.js, every filter, every view, and check.js last. Adding a filter or
view means adding one file; this module picks it up.
"""

import html
import json
from pathlib import Path

PAGE_DIR = Path(__file__).with_name("page")


def js_files() -> list[Path]:
    """Page scripts in the order they must load."""
    return [
        PAGE_DIR / "core.js",
        PAGE_DIR / "metrics.js",
        *sorted((PAGE_DIR / "filters").glob("*.js")),
        *sorted((PAGE_DIR / "views").glob("*.js")),
        PAGE_DIR / "check.js",
    ]


def _script(path: Path) -> str:
    code = path.read_text(encoding="utf-8")
    if "</script" in code.lower():
        raise ValueError(f"{path.name} contains '</script', which would end the page")
    name = path.relative_to(PAGE_DIR).as_posix()
    return f"<script>\n/* {name} */\n{code}\n</script>"


def render(data: dict, title: str) -> str:
    # "</" inside the embedded JSON would end the <script> element early.
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    blob = blob.replace("</", "<\\/")
    template = (PAGE_DIR / "template.html").read_text(encoding="utf-8")
    scripts = "\n".join(_script(p) for p in js_files())
    return (
        template.replace("__TITLE__", html.escape(title))
        .replace("__DATA__", blob)
        .replace("__SCRIPTS__", scripts)
    )


def write(data: dict, title: str, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, title), encoding="utf-8")
    return out
