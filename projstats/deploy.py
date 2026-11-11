"""Build the whole site: one page per listed project, plus index.html."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config, export, page, storage

GA_ID = re.compile(r"G-[A-Z0-9]+")

# The Google tag as Google displays it.
GA_TAG = """<script async src="https://www.googletagmanager.com/gtm.js?id={id}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
</script>
"""


@dataclass
class DeployList:
    projects: list[Path]  # config files, in the order the page switcher shows them
    index: Path  # the project whose page is also index.html


def load_list(path: str | Path) -> DeployList:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - {"projects", "index"}
    if unknown:
        raise ValueError(f"{path}: unknown setting(s): {', '.join(sorted(unknown))}")
    names = data.get("projects")
    if not isinstance(names, list) or not names:
        raise ValueError(f"{path}: projects must be a list of config files")
    if not all(isinstance(n, str) and n for n in names):
        raise ValueError(f"{path}: projects must be a list of config files")
    index = data.get("index")
    if index not in names:
        raise ValueError(f"{path}: index must be one of the projects")
    return DeployList([path.parent / n for n in names], path.parent / index)


def add_tag(text: str, ga_id: str) -> str:
    if not GA_ID.fullmatch(ga_id):
        raise ValueError(f"Google tag ID must look like G-XXXXXXXXXX, got {ga_id!r}")
    head = "<head>\n"
    if head not in text:
        raise ValueError("the page has no <head> line to put the Google tag after")
    return text.replace(head, head + GA_TAG.format(id=ga_id), 1)


def build(listing: DeployList, out_dir: str | Path, ga_id: str | None = None):
    """Write each listed project's page and index.html into `out_dir`, remove
    other .html files there, and return the paths written."""
    cfgs = [config.load(p) for p in listing.projects]
    slugs = [c.slug for c in cfgs]
    if len(set(slugs)) != len(slugs):
        raise ValueError("two listed projects are the same repository")
    for path, cfg in zip(listing.projects, cfgs, strict=True):
        if not cfg.db_path.exists():
            raise ValueError(f"{path}: no database at {cfg.db_path}; run fetch first")

    texts = {}
    for cfg in cfgs:
        conn = storage.connect(cfg.db_path)
        data = export.build(conn, cfg)
        conn.close()
        data["siblings"] = page.switcher(cfgs, cfg)
        text = page.render(data, page.title(cfg))
        texts[f"{cfg.slug}.html"] = add_tag(text, ga_id) if ga_id else text
    index_cfg = cfgs[listing.projects.index(listing.index)]
    texts["index.html"] = texts[f"{index_cfg.slug}.html"]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.html"):
        if old.name not in texts:
            old.unlink()
    written = []
    for name, text in texts.items():
        written.append(out_dir / name)
        written[-1].write_text(text, encoding="utf-8")
    return written
