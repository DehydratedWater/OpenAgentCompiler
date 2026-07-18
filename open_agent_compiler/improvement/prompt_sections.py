"""Structured, per-section prompts — optimisable without gutting.

Motivation. A rich agent system prompt is thousands of chars of carefully
layered instructions (persona, planning protocol, capability rules, voice,
examples). The autoloop's `LLMPromptRewriter` rewrites the WHOLE prompt as one
string, so a single mutation can silently drop or compress half of it — the
optimiser "improves" a probe score while quietly deleting hard-won structure.
The only guard so far was `--preserve-prompt` (identity-only: never change it),
which is a bandaid — it trades all improvement for safety.

This module makes the prompt a STRUCTURED list of named `PromptSection` objects.
Each section is a first-class, independently-optimisable unit with metadata the
optimiser respects:

  - `required=True`  → the section may be REWRITTEN but never REMOVED/emptied.
  - `mutable=False`  → frozen verbatim (e.g. the delivery contract, safety rules).

The section-aware mutator (`open_agent_compiler.improvement.mutators.sectioned`) rewrites ONE
mutable section's content at a time, leaving every other section byte-identical.
So the autoloop gets fine-grained, accumulating improvement (fix the planning
section, then the voice section, …) with a structural guarantee that the rich
scaffold survives. The rendered `system_prompt` is derived from the sections, so
every existing consumer (compiler, snapshot, eval) keeps working unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# The definition key that holds the structured sections. When present, the
# rendered system_prompt is DERIVED from it (see apply_sections_to_definition),
# so prompt_sections is the source of truth and system_prompt is the cache.
SECTIONS_KEY = "prompt_sections"


class PromptSection(BaseModel):
    """One named, independently-optimisable slice of a system prompt."""

    name: str
    content: str
    # What this section is for — fed to the optimiser so a section rewrite is
    # on-target (the LLM knows the section's JOB, not just its current text).
    purpose: str = ""
    # required: the optimiser may rewrite this section but must never drop it or
    # leave it empty (the structural guarantee).
    required: bool = True
    # mutable: if False the section is frozen verbatim (delivery contract, safety
    # rails, capability assertions you never want softened).
    mutable: bool = True
    # Stable render order; ties broken by list position.
    order: int = 0

    def render(self) -> str:
        return self.content.strip()


def _coerce(section: PromptSection | dict[str, Any]) -> PromptSection:
    return section if isinstance(section, PromptSection) else PromptSection(**section)


def render_sections(sections: list[PromptSection | dict[str, Any]]) -> str:
    """Concatenate sections (stable order) into a single system-prompt string.

    Pure. Empty sections contribute nothing. Order is by `.order` then original
    position, so a mutated section never reshuffles the prompt.
    """
    coerced = [_coerce(s) for s in sections]
    indexed = sorted(enumerate(coerced), key=lambda it: (it[1].order, it[0]))
    parts = [s.render() for _, s in indexed if s.render()]
    return "\n\n".join(parts)


# A markdown ATX header (## Title) — the natural section boundary in the
# hand-authored rich prompts. Capturing the header lets us name each section.
_HEADER_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return s or "section"


def split_into_sections(
    prompt: str,
    *,
    immutable_names: set[str] | None = None,
    required_names: set[str] | None = None,
) -> list[PromptSection]:
    """Parse a markdown-headed prompt into PromptSections (one per top header).

    The text BEFORE the first header becomes a leading "intro" section. Each
    `## Header` (or any ATX level) starts a new section whose `name` is the
    slugified header and whose `content` includes the header line + its body.
    Names are de-duplicated. `immutable_names`/`required_names` (matched against
    the slug) tune the metadata so callers can freeze e.g. the delivery contract.

    Round-trips: render_sections(split_into_sections(p)) preserves p up to
    whitespace between blocks.
    """
    immutable_names = immutable_names or set()
    required_names = required_names or set()
    matches = list(_HEADER_RE.finditer(prompt))
    sections: list[PromptSection] = []
    seen: dict[str, int] = {}

    def _add(name: str, content: str, order: int) -> None:
        content = content.strip()
        if not content:
            return
        base = name
        if base in seen:
            seen[base] += 1
            name = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        sections.append(
            PromptSection(
                name=name,
                content=content,
                mutable=base not in immutable_names,
                required=(base in required_names) or True,
                order=order,
            )
        )

    if not matches:
        # No headers — one mutable blob. Still optimisable as a single section.
        _add("body", prompt, 0)
        return sections

    intro = prompt[: matches[0].start()].strip()
    order = 0
    if intro:
        _add("intro", intro, order)
        order += 1
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
        block = prompt[m.start() : end]
        _add(_slug(m.group(2)), block, order)
        order += 1
    return sections


def apply_sections_to_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """If the definition carries prompt_sections, (re)derive system_prompt.

    Returns a NEW dict (does not mutate input). No-op when prompt_sections is
    absent, so non-sectioned agents are untouched. This is the single point
    where structured sections collapse to the flat string the compiler emits.
    """
    sections = definition.get(SECTIONS_KEY)
    if not sections:
        return dict(definition)
    out = dict(definition)
    out["system_prompt"] = render_sections(sections)
    return out


def get_sections(definition: dict[str, Any]) -> list[PromptSection]:
    """Read the structured sections from a definition (empty if none)."""
    return [_coerce(s) for s in (definition.get(SECTIONS_KEY) or [])]


def set_sections(
    definition: dict[str, Any], sections: list[PromptSection | dict[str, Any]]
) -> dict[str, Any]:
    """Return a new definition with sections set AND system_prompt re-derived."""
    out = dict(definition)
    out[SECTIONS_KEY] = [_coerce(s).model_dump() for s in sections]
    out["system_prompt"] = render_sections(sections)
    return out
