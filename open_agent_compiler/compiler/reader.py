"""Read a compiled agent artifact back into its parts.

The compiler WRITES `.opencode/agents/<name>.md` (YAML frontmatter +
system-prompt body). This reads one back — the ~15 lines every consumer that
runs a pure-prompt ("function") agent itself was re-implementing (multiple
downstream projects carried their own `parse_compiled_agent` copies). The
framework owns the *artifact format*,
so it should own reading it; execution stays the consumer's choice (one API
call, LangChain, opencode — not the framework's business).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class CompiledAgent(BaseModel):
    """The parsed pieces of a compiled agent `.md`."""

    name: str
    model: str | None = None
    system_prompt: str = ""
    frontmatter: dict[str, Any] = Field(default_factory=dict)


def parse_compiled_agent(text: str, *, name: str = "") -> CompiledAgent:
    """Parse compiled-agent markdown text into a CompiledAgent."""
    if text.startswith("---"):
        # ---\n<yaml>\n---\n<body>.  Split into ['', yaml, body]; the body may
        # itself contain '---' (markdown rules) — only the first two split.
        _, front, body = text.split("---", 2)
        frontmatter = yaml.safe_load(front) or {}
        system_prompt = body.lstrip("\n")
    else:
        frontmatter = {}
        system_prompt = text
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return CompiledAgent(
        name=name,
        model=frontmatter.get("model"),
        system_prompt=system_prompt,
        frontmatter=frontmatter,
    )


def load_compiled_agent(path: str | Path) -> CompiledAgent:
    """Read + parse a compiled agent `.md` from disk."""
    p = Path(path)
    return parse_compiled_agent(p.read_text(encoding="utf-8"), name=p.stem)
