"""Load a project config file (projects/<name>.toml)."""

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class RepoConfig:
    github: str = ""  # "owner/name"
    url: str = ""  # clone URL; defaults to the GitHub URL
    label: str = ""  # short name shown on the page; defaults to `github`


@dataclass
class PeopleConfig:
    bots: list[str] = field(default_factory=list)
    # Checkboxes the page offers to leave a person out of every count: the
    # label shown on the page (not their name) -> their GitHub login.
    leave_out_option: dict[str, str] = field(default_factory=dict)


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
    enabled: bool = False  # false: analytics only; no tagging, no Themes tab or filter
    about: str = ""  # one sentence about the project, for the tagging prompt
    areas: str = ""  # the project's main areas, so themes name a specific one
    # Names of the project itself; themes like "<name> support" get dropped.
    project_names: list[str] = field(default_factory=list)
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
    # Segments by share of all activity: core is the top group that together
    # does `core_share` of it, regular the next group up to `regular_share`.
    core_share: float = 0.80
    regular_share: float = 0.90


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
    opt = people.leave_out_option
    if not isinstance(opt, dict) or not all(
        isinstance(k, str) and k.strip() and isinstance(v, str) and v for k, v in opt.items()
    ):
        raise ValueError('[people] leave_out_option must map labels to GitHub logins, e.g. { maintainer = "login" }')
    ex = activity.exclude_items
    if not isinstance(ex, list) or not all(type(n) is int and n > 0 for n in ex):
        raise ValueError("[activity] exclude_items must be PR or issue numbers")
    r = retention
    if not 0 < r.core_share < r.regular_share <= 1 or r.return_gap_days <= 0:
        raise ValueError(
            "[retention] needs return_gap_days > 0 and "
            "0 < core_share < regular_share <= 1"
        )
    t = themes
    if type(t.enabled) is not bool:
        raise ValueError("[themes] enabled must be true or false")
    if min(t.max_per_doc, t.doc_chars, t.batch_docs, t.batch_chars) < 1:
        raise ValueError("[themes] limits must be at least 1")
    names = t.project_names
    if not isinstance(names, list) or not all(isinstance(x, str) and x for x in names):
        raise ValueError("[themes] project_names must be a list of names")
    try:
        groups = re.compile(releases.tag_pattern).groups
    except re.error as e:
        raise ValueError(f"[releases] tag_pattern is not a valid regex: {e}") from e
    if groups < 3:
        raise ValueError("[releases] tag_pattern must capture major, minor, and patch")
    return cfg
