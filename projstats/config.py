"""Load a project config file (projects/<name>.toml)."""

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
class RetentionConfig:
    return_gap_days: int = 365  # back after at least this long away = "returning"
    core_quarters: int = 12  # core: active in at least this many distinct quarters
    regular_quarters: int = 4  # regular: at least this many, below core


@dataclass
class Config:
    data_dir: str = "data"
    repo: RepoConfig = field(default_factory=RepoConfig)
    people: PeopleConfig = field(default_factory=PeopleConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)

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
    retention = _build(RetentionConfig, data.pop("retention", {}), "[retention]")
    sections = {"repo": repo, "people": people, "retention": retention}
    cfg = _build(Config, {**data, **sections}, "top-level")
    owner, _, name = repo.github.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(f'[repo] github must be "owner/name", got {repo.github!r}')
    r = retention
    if not 0 < r.regular_quarters < r.core_quarters or r.return_gap_days <= 0:
        raise ValueError(
            "[retention] needs return_gap_days > 0 and "
            "0 < regular_quarters < core_quarters"
        )
    return cfg
