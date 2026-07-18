"""Section-aware prompt mutator — improve ONE section, keep the rest verbatim.

Where `LLMPromptRewriter` rewrites the whole system_prompt as one string (and
can silently drop structure), `SectionRewriterMutator` targets a SINGLE named
`PromptSection`: it asks the LLM to improve just that section's content, then
re-renders the prompt with every other section byte-identical. Required sections
are never emptied; immutable sections get no mutator at all.

Use `make_section_mutators(definition, ...)` to build one mutator per mutable
section — the loop then emits one candidate per section per round (each differs
from the parent by exactly one improved section), and the best section-level
improvement is promoted. Over rounds the winner accumulates per-section gains
with a structural guarantee that the rich scaffold survives.
"""

from __future__ import annotations

from typing import Any

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.prompt_sections import (
    SECTIONS_KEY,
    get_sections,
    render_sections,
)
from open_agent_compiler.improvement.version import ComponentVersion

_SECTION_GUIDANCE = (
    "You are improving ONE section of a larger agent system prompt. Rewrite ONLY"
    " this section to better fulfil its stated PURPOSE and to address the listed"
    " failures. Keep — or increase — its detail and specificity; do NOT shorten"
    " for brevity's sake and do NOT delete instructions. Do not add capabilities"
    " from other sections. Preserve the section's leading markdown header line"
    " verbatim. Return ONLY the rewritten section text."
)


class SectionRewriterMutator(Mutator):
    """Rewrite a single named section's content via the LLM.

    Returns None (skips) when: not an agent, no llm, no sections, the target
    section is absent or immutable, or the rewrite is empty/unchanged. A
    `required` section is never returned emptied (empty rewrite → skip), so the
    structural guarantee holds.
    """

    def __init__(
        self, section_name: str, *, model: str | None = None, name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"section-rewriter:{section_name}")
        self.section_name = section_name
        self.model = model

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent" or ctx.llm is None:
            return None
        defn = dict(version.definition or {})
        sections = get_sections(defn)
        if not sections:
            return None
        idx = next(
            (i for i, s in enumerate(sections) if s.name == self.section_name), None
        )
        if idx is None:
            return None
        target = sections[idx]
        if not target.mutable or not target.content.strip():
            return None

        criterion_dict = (
            ctx.criterion.model_dump()
            if getattr(ctx, "criterion", None) is not None
            else None
        )
        guidance = _SECTION_GUIDANCE
        if target.purpose:
            guidance += f"\n\nThis section's PURPOSE: {target.purpose}"
        try:
            rewritten = ctx.llm.rewrite(
                target=target.content,
                guidance=guidance,
                context={
                    "section_name": target.name,
                    "section_purpose": target.purpose,
                    "failures": ctx.failures,
                    "criterion": criterion_dict,
                },
                model=self.model,
            )
        except Exception:  # noqa: BLE001 — degrade gracefully
            return None
        rewritten = (rewritten or "").strip()
        # Structural guarantee: a required section is never dropped/emptied.
        if not rewritten or rewritten == target.content.strip():
            return None

        new_sections = [s.model_copy() for s in sections]
        new_sections[idx] = new_sections[idx].model_copy(update={"content": rewritten})
        defn[SECTIONS_KEY] = [s.model_dump() for s in new_sections]
        defn["system_prompt"] = render_sections(new_sections)
        return ComponentVersion.of(
            component_id=version.component_id,
            kind=version.kind,
            definition=defn,
            parent_hash=version.content_hash,
            author=self.name,
        )


def make_section_mutators(
    definition: dict[str, Any], *, model: str | None = None,
) -> list[SectionRewriterMutator]:
    """One SectionRewriterMutator per MUTABLE section of the definition.

    Immutable sections are skipped (no mutator → never touched). Returns [] when
    the definition carries no structured sections, so callers can fall back to
    the flat-string rewriter for non-sectioned agents.
    """
    return [
        SectionRewriterMutator(s.name, model=model)
        for s in get_sections(definition)
        if s.mutable and s.content.strip()
    ]
