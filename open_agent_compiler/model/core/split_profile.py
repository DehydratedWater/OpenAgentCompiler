"""SplitProfile — VariantSpec that routes presets by agent model_class.

A regular VariantSpec applies one preset to every agent in a pass. A
SplitProfile is a VariantSpec where the preset depends on the agent's
declared `model_class` — fast/analytical/vision/... — so a single
compilation pass can fan out a tree across multiple co-located models:

    SplitProfile(
        name="qwen35-split",
        postfix="-splitqwen35",
        class_map={
            "fast": qwen35_35b_a3b_preset,        # speed-optimized
            "analytical": qwen35_27b_heretic_preset,
        },
        preset=qwen35_27b_heretic_preset,         # used as fallback
        default_class="analytical",
    )

The agent declares its class once at definition time:

    AgentDefinition(..., model_class="fast")

When compiled under the split profile above, that agent binds to the
fast preset; siblings with model_class="analytical" bind to the deeper
one. This replaces the hand-rolled SplitProfile pattern that large
pre-framework deployments carried in their own config modules.
"""

from __future__ import annotations


from pydantic import ConfigDict, Field, model_validator

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.model_preset import ModelPreset
from open_agent_compiler.model.core.variant_spec import VariantSpec


class SplitProfile(VariantSpec):
    """VariantSpec that picks a preset per agent based on model_class.

    `class_map` is the routing table. `default_class` is consulted when an
    agent's model_class is not in the table — if `default_class` is also
    not present, the spec's own `preset` is used (matching base VariantSpec
    behavior so an agent without a model_class still compiles).
    """

    model_config = ConfigDict(frozen=True)

    class_map: dict[str, ModelPreset] = Field(default_factory=dict)
    default_class: str = "default"
    passthrough_classes: tuple[str, ...] = Field(
        default=("vision",),
        description=(
            "Model classes the split does NOT touch — the agent keeps its own"
            " original model. Mirrors the resolve()->None-for-'vision' rule from"
            " the original deployments, so image/video/document agents aren't"
            " rerouted onto a text model when"
            " a split profile is applied. Set to () to split every class."
        ),
    )

    @model_validator(mode="after")
    def _class_map_non_empty(self) -> "SplitProfile":
        if not self.class_map:
            raise ValueError(
                "SplitProfile.class_map must contain at least one entry; use"
                " VariantSpec for single-preset variants."
            )
        return self

    def applies_to(self, variant: AgentVariant) -> bool:
        """Opt passthrough-class agents out of the split entirely.

        `apply_variant` returns the variant unchanged when this is False, so a
        vision agent keeps its original model instead of being rerouted to a
        text preset — the parity-critical 'keep original' semantic carried
        over from the pre-framework implementations.
        """
        return variant.agent_definition.model_class not in self.passthrough_classes

    def preset_for(self, variant: AgentVariant) -> ModelPreset:
        model_class = variant.agent_definition.model_class
        if model_class in self.class_map:
            return self.class_map[model_class]
        if self.default_class in self.class_map:
            return self.class_map[self.default_class]
        return self.preset
