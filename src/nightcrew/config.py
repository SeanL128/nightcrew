"""Loaders for the two config files (ADR-19, ADR-22).

- Per-repo ``nightcrew.yaml``: ``config`` header (test_cmd, off_limits,
  conventions) + ``items``. The shared contract from ``lite/``.
- Engine-level ``fleet.json``: multi-repo list (seeded from autodev's), plus
  an optional ``dispatch`` section selecting the seam backend per role.

Secrets come from env only — never from these files.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .caps import Caps


class ConfigError(Exception):
    pass


@dataclass
class Item:
    id: str
    description: str
    acceptance_criteria: list[str]
    deps: list[str] = field(default_factory=list)


@dataclass
class RepoSpec:
    test_cmd: str
    off_limits: list[str]
    conventions: str
    items: list[Item]


def load_repo_spec(repo: Path) -> RepoSpec:
    path = Path(repo) / "nightcrew.yaml"
    if not path.exists():
        raise ConfigError(f"no nightcrew.yaml in {repo}")
    data = yaml.safe_load(path.read_text()) or {}
    cfg = data.get("config") or {}
    if not cfg.get("test_cmd"):
        raise ConfigError("config.test_cmd is required (the gate re-runs it)")
    items = []
    for raw in data.get("items") or []:
        if not raw.get("id"):
            raise ConfigError(f"item missing id: {raw!r}")
        items.append(
            Item(
                id=raw["id"],
                description=(raw.get("description") or "").strip(),
                acceptance_criteria=[str(c) for c in raw.get("acceptance_criteria") or []],
                deps=list(raw.get("deps") or []),
            )
        )
    return RepoSpec(
        test_cmd=cfg["test_cmd"],
        off_limits=list(cfg.get("off_limits") or []),
        conventions=cfg.get("conventions") or "",
        items=items,
    )


@dataclass
class Repo:
    name: str
    github: str
    enabled: bool = True
    priority: int = 100
    trust: str = "propose_only"
    max_items_per_run: int = 1
    path: str = ""  # local checkout; resolved at run time if empty


@dataclass
class Fleet:
    repos: list[Repo]
    dispatch: dict  # seam config, passed verbatim to nightcrew.dispatch
    caps: Caps = field(default_factory=Caps)


def load_fleet(path: Path) -> Fleet:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"no fleet file at {path}")
    data = json.loads(path.read_text())
    repos = [Repo(**{k: v for k, v in r.items() if k in Repo.__dataclass_fields__})
             for r in data.get("repos") or []]
    if not repos:
        raise ConfigError("fleet.json has no repos")
    caps = data.get("caps") or {}
    return Fleet(
        repos=repos,
        dispatch=data.get("dispatch") or {},
        caps=Caps(**{k: v for k, v in caps.items() if k in Caps.__dataclass_fields__}),
    )
