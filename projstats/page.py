"""Write the self-contained web page: template + embedded data + page scripts.

The page's code lives in projstats/page/ as small files: core.js first, then
metrics.js, charts.js, every filter, every view, and check.js last. Adding a
filter or view means adding one file; this module picks it up.
"""

import html
import json
import os
from pathlib import Path

from . import config

PAGE_DIR = Path(__file__).with_name("page")


def js_files() -> list[Path]:
    """Page scripts in the order they must load."""
    return [
        PAGE_DIR / "core.js",
        PAGE_DIR / "metrics.js",
        PAGE_DIR / "charts.js",
        *sorted((PAGE_DIR / "filters").glob("*.js")),
        *sorted((PAGE_DIR / "views").glob("*.js")),
        PAGE_DIR / "check.js",
    ]


def _neighbours(config_path: str | Path):
    """Every config next to this one that loads, as (path, config). A config
    that doesn't load is skipped."""
    for path in sorted(Path(config_path).parent.glob("*.toml")):
        try:
            yield path, config.load(path)
        except (ValueError, OSError):
            continue


def _page_path(cfg: config.Config) -> Path:
    return Path(cfg.data_dir) / f"{cfg.slug}.html"


def siblings(config_path: str | Path, cfg: config.Config, out: Path) -> list[dict]:
    """The projects the page can switch to: every config next to this one whose
    page already exists, plus this project. Links are relative to `out`, so the
    pages must stay together."""
    found = []
    for _, other in _neighbours(config_path):
        target = _page_path(other)
        current = other.slug == cfg.slug
        if not current and not target.exists():
            continue
        href = Path(os.path.relpath(target, out.parent)).as_posix()
        name = other.repo.github.split("/")[-1]
        found.append({"name": name, "href": href, "current": current})
    return found


def other_pages(config_path: str | Path, cfg: config.Config):
    """The other projects whose page already exists, as (path, config). Their
    switchers are fixed when they are built, so a new page leaves them stale
    until they are built again."""
    return [
        (path, other)
        for path, other in _neighbours(config_path)
        if other.slug != cfg.slug and _page_path(other).exists()
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
