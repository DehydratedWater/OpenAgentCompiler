"""SkillBundle — one piece of developer documentation for a coding agent."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DialectTarget = Literal["opencode", "claude"]


class SkillBundle(BaseModel):
    """A self-contained skill: name, summary, body, dialect targets, version.

    `version` is bumped whenever the content changes so sync-skills can
    detect drift via a sidecar file. `content_hash` is a derived sha256
    used for drift detection; users edit `version` by hand when they
    intentionally fork content.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    body_markdown: str
    targets: tuple[DialectTarget, ...] = ("opencode", "claude")
    version: str = "1.0.0"
    tools_hint: tuple[str, ...] = Field(
        default=(),
        description=(
            "Optional list of tool / file names this skill especially"
            " expects the agent to use. Surfaced in the SKILL.md preamble."
        ),
    )

    @property
    def content_hash(self) -> str:
        canonical = f"{self.name}|{self.version}|{self.body_markdown}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
