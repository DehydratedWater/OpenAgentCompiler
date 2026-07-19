"""Universal compiled-artifact introspection — one loader for every dialect.

Capability tests assert against the in-memory permission dict (already
dialect-independent); what was missing is asserting against the
COMPILED ARTIFACT — "did the pi build really deny write?", "does the
codex TOML carry the sandbox mode?" — without per-dialect parsing in
every test. `load_agent_artifact` reads any dialect's compiled agent
into one shape:

    art = load_agent_artifact(build_dir, "primary", dialect="codex")
    art.config["sandbox_mode"]     # parsed frontmatter/TOML dict
    art.body                       # the prompt text (markdown / developer_instructions)
    art.path                       # the file it came from

`list_agent_artifacts` enumerates a build tree's compiled agents for a
dialect. Both raise FileNotFoundError with the looked-up path when the
agent isn't compiled — a missing artifact is a test failure, not a skip.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_AGENT_DIRS = {
    "opencode": (Path(".opencode") / "agents", ".md"),
    "claude": (Path(".claude") / "agents", ".md"),
    "pi": (Path(".pi") / "agents", ".md"),
    "codex": (Path(".codex") / "agents", ".toml"),
}


class AgentArtifact(BaseModel):
    """One compiled agent, dialect-normalized."""

    model_config = ConfigDict(frozen=True)

    dialect: str
    agent_name: str
    path: Path
    config: dict = Field(
        description=(
            "The structured half: YAML frontmatter (markdown dialects) or"
            " the full TOML table (codex)."
        ),
    )
    body: str = Field(
        description=(
            "The prompt half: markdown body, or codex's"
            " developer_instructions."
        ),
    )


def agents_dir(build_dir: Path, dialect: str) -> Path:
    if dialect not in _AGENT_DIRS:
        raise ValueError(
            f"unknown dialect {dialect!r}; supported: {sorted(_AGENT_DIRS)}"
        )
    sub, _ = _AGENT_DIRS[dialect]
    return build_dir / sub


def list_agent_artifacts(build_dir: Path, dialect: str) -> list[str]:
    """Compiled agent names present in the build tree for `dialect`."""
    sub, ext = _AGENT_DIRS[dialect] if dialect in _AGENT_DIRS else (None, None)
    if sub is None:
        raise ValueError(
            f"unknown dialect {dialect!r}; supported: {sorted(_AGENT_DIRS)}"
        )
    directory = build_dir / sub
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob(f"*{ext}"))


def _parse_markdown(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            return (frontmatter if isinstance(frontmatter, dict) else {},
                    parts[2].strip())
    return {}, text.strip()


def load_agent_artifact(
    build_dir: Path, agent_name: str, *, dialect: str,
) -> AgentArtifact:
    """Read one compiled agent from any dialect's build tree."""
    if dialect not in _AGENT_DIRS:
        raise ValueError(
            f"unknown dialect {dialect!r}; supported: {sorted(_AGENT_DIRS)}"
        )
    sub, ext = _AGENT_DIRS[dialect]
    path = build_dir / sub / f"{agent_name}{ext}"
    if not path.exists():
        raise FileNotFoundError(
            f"no compiled {dialect} agent {agent_name!r} at {path}"
        )
    text = path.read_text()
    if dialect == "codex":
        data = tomllib.loads(text)
        body = str(data.get("developer_instructions", ""))
        config = {k: v for k, v in data.items() if k != "developer_instructions"}
    else:
        config, body = _parse_markdown(text)
    return AgentArtifact(
        dialect=dialect, agent_name=agent_name, path=path,
        config=config, body=body,
    )
