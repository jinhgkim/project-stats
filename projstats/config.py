"""Load a project config file (projects/<name>.toml)."""

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class RepoConfig:
    github: str = ""  # "owner/name"
    url: str = ""  # clone URL; defaults to the GitHub URL


@dataclass
class PeopleConfig:
    bots: list[str] = field(default_factory=list)


@dataclass
class ActivityConfig:
    # PR or issue numbers left out of every count, with commits linked to those PRs.
    exclude_items: list[int] = field(default_factory=list)


@dataclass
class ReleasesConfig:
    # Fully matches final release tags; captures major, minor, patch[, fourth].
    tag_pattern: str = r"^v?(\d+)\.(\d+)\.(\d+)$"


@dataclass
class ThemesConfig:
    about: str = ""  # one sentence about the project, for the tagging prompt
    max_per_doc: int = 3  # themes per document
    doc_chars: int = 1500  # each document's text is cut at this length
    batch_docs: int = 8  # documents per model call...
    batch_chars: int = 8000  # ...or fewer, if their text adds up to this
    registry_limit: int = 300  # existing themes listed in the prompt


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "ornith-1.5:9b"
    timeout: float = 600  # seconds per request
    context: int = 32768  # tokens the model can see per request (prompt + answer)
    think: bool = False  # let the model reason first: slower, sometimes more careful


@dataclass
class RetentionConfig:
    return_gap_days: int = 365  # back after at least this long away = "returning"
    core_quarters: int = 12  # core: active in at least this many distinct quarters
    regular_quarters: int = 4  # regular: at least this many, below core


@dataclass
class Config:
    data_dir: str = "data"
    repo: RepoConfig = field(default_factory=RepoConfig)
    people: PeopleConfig = field(default_factory=PeopleConfig)
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    releases: ReleasesConfig = field(default_factory=ReleasesConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    themes: ThemesConfig = field(default_factory=ThemesConfig)

    @property
    def slug(self) -> str:
        return self.repo.github.replace("/", "__")

    @property
    def clone_url(self) -> str:
        return self.repo.url or f"https://github.com/{self.repo.github}.git"

    @property
    def clone_path(self) -> Path:
        return Path(self.data_dir) / "repos" / f"{self.slug}.git"

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / f"{self.slug}.db"


def _build(cls, data: dict, section: str):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown {section} setting(s): {', '.join(sorted(unknown))}")
    return cls(**data)


def load(path: str | Path) -> Config:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    repo = _build(RepoConfig, data.pop("repo", {}), "[repo]")
    people = _build(PeopleConfig, data.pop("people", {}), "[people]")
    activity = _build(ActivityConfig, data.pop("activity", {}), "[activity]")
    retention = _build(RetentionConfig, data.pop("retention", {}), "[retention]")
    releases = _build(ReleasesConfig, data.pop("releases", {}), "[releases]")
    ollama = _build(OllamaConfig, data.pop("ollama", {}), "[ollama]")
    themes = _build(ThemesConfig, data.pop("themes", {}), "[themes]")
    sections = {
        "themes": themes,
        "ollama": ollama,
        "releases": releases,
        "repo": repo,
        "people": people,
        "activity": activity,
        "retention": retention,
    }
    cfg = _build(Config, {**data, **sections}, "top-level")
    owner, _, name = repo.github.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(f'[repo] github must be "owner/name", got {repo.github!r}')
    ex = activity.exclude_items
    if not isinstance(ex, list) or not all(type(n) is int and n > 0 for n in ex):
        raise ValueError("[activity] exclude_items must be PR or issue numbers")
    r = retention
    if not 0 < r.regular_quarters < r.core_quarters or r.return_gap_days <= 0:
        raise ValueError(
            "[retention] needs return_gap_days > 0 and "
            "0 < regular_quarters < core_quarters"
        )
    t = themes
    if min(t.max_per_doc, t.doc_chars, t.batch_docs, t.batch_chars) < 1:
        raise ValueError("[themes] limits must be at least 1")
    try:
        groups = re.compile(releases.tag_pattern).groups
    except re.error as e:
        raise ValueError(f"[releases] tag_pattern is not a valid regex: {e}") from e
    if groups < 3:
        raise ValueError("[releases] tag_pattern must capture major, minor, and patch")
    return cfg
