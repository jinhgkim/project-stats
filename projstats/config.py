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
class Config:
    data_dir: str = "data"
    repo: RepoConfig = field(default_factory=RepoConfig)
    people: PeopleConfig = field(default_factory=PeopleConfig)

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
    cfg = _build(Config, {**data, "repo": repo, "people": people}, "top-level")
    owner, _, name = repo.github.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(f'[repo] github must be "owner/name", got {repo.github!r}')
    return cfg
