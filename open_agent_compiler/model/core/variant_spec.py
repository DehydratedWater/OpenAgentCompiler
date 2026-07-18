"""VariantSpec — multi-variant compilation as a first-class primitive.

A VariantSpec describes one pass over the same agent tree with a
different model / postfix / extra-providers set. Multiple specs in one
CompileScript invocation produce side-by-side compiled trees:

    .opencode/agents/persona/orch.md           # default (no postfix)
    .opencode/agents/persona/orch-glm47.md     # -glm47 variant
    .opencode/agents/persona/orch-qwen35.md    # -qwen35 variant

This replaces the reset-the-model-globals hack pre-framework deployments
relied on — instead of mutating
module-level globals before each compile pass, the compiler reads the
VariantSpec for that pass and applies the preset/postfix locally.

Phase 2.1 establishes the data model + a `replace_preset` helper that
later phases (2.2 SplitProfile, 2.5 multi-write) use to derive the
per-agent effective preset.

Feature flags live here too so consumers stop reaching for module
globals like `is_compiling_local()` — Phase 2.3 wires them into the
CompilationContext that flows through the compiler.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.model_preset import ModelPreset


class VariantSpec(BaseModel):
    """One compilation pass over the same agent tree.

    `postfix` (str, may be empty for the default variant) gets appended
    to every compiled agent's file stem. `preset` is the model applied
    to agents in this pass. `extra_providers` lets the dialect emit
    additional provider config blocks (e.g. when the variant uses one
    base model plus a vision fall-back). `feature_flags` are surfaced
    by the CompilationContext so agent factories can branch at compile
    time without touching globals.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    postfix: str = ""
    preset: ModelPreset
    extra_providers: tuple[ModelPreset, ...] = ()
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None

    @model_validator(mode="after")
    def _name_non_empty(self) -> "VariantSpec":
        if not self.name.strip():
            raise ValueError("VariantSpec.name must be non-empty")
        return self

    def applies_to(self, variant: AgentVariant) -> bool:
        """Hook for Phase 2.2 SplitProfile to opt out per-agent."""
        return True

    def preset_for(self, variant: AgentVariant) -> ModelPreset:
        """Effective preset for `variant` under this spec.

        Base VariantSpec returns its own preset for every agent. The
        SplitProfile subclass (Phase 2.2) picks per-agent based on the
        agent's model_class.
        """
        return self.preset


def apply_variant(spec: VariantSpec, variant: AgentVariant) -> AgentVariant:
    """Return a copy of `variant` with `spec`'s preset + postfix applied.

    Uses Pydantic model_copy so the original variant stays untouched —
    multi-variant compilation safely re-uses the same resolved tree.
    """
    if not spec.applies_to(variant):
        return variant
    new_preset = spec.preset_for(variant)
    return variant.model_copy(
        update={
            "model_parameters": new_preset.to_model_parameters(),
            "postfix": spec.postfix,
        }
    )
