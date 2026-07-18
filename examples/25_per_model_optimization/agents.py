"""Same agent optimised independently per model class.

The baseline prompt is the same across classes ("you are a quick
assistant, answer in one sentence"). For each model class in the
SplitProfile, the loop runs its own evolution:

- fast (glm-4.5-air) — small / cheap; the loop tends to find tight,
  imperative prompts that compensate for the smaller context window.
- analytical (glm-5.1) — heavier; the loop can use a richer prompt
  because the model handles longer instructions well.

The winning prompts for the two classes differ, and the snapshots land
under improved/<component>/<class>/<hash>.json so you can promote the
right one per model.
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    ModelPreset,
    OptimisationCriterion,
    SamplingDefaults,
    SplitProfile,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.improvement import Criterion


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    explainer = AgentDefinition(
        header=AgentHeader(
            agent_id="multi-model-explainer",
            name="multi-model-explainer",
            description="Explains a software concept; per-model optimised.",
        ),
        usage_explanation_long=(
            "Reads a software question and returns an explanation."
            " The exact prompt that produces the best answer differs per"
            " model, so this agent gets a per-class optimisation loop."
        ),
        usage_explanation_short="per-model-optimised explainer",
        system_prompt=(
            "You are a quick assistant. Answer the user in one sentence."
            " Be brief."
        ),
        model_class="default",  # overridden per-class in run_per_class_loops
    )

    agent_id = reg.register_agent(
        "multi-model-explainer",
        explainer,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    )

    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


# The SplitProfile drives per-class evolution. Each class binds to one
# preset; the evaluator reads version.definition['model_class'] to
# pick which model to invoke the candidate against.
SPLIT_PROFILE = SplitProfile(
    name="per-model",
    postfix="-permodel",
    preset=ModelPreset(
        name="fallback",
        provider="zai-coding-plan",
        model_id="glm-4.5-air",
        sampling=SamplingDefaults(temperature=0.3),
    ),
    class_map={
        "fast": ModelPreset(
            name="fast-glm45",
            provider="zai-coding-plan",
            model_id="glm-4.5-air",
            sampling=SamplingDefaults(temperature=0.3),
        ),
        "analytical": ModelPreset(
            name="analytical-glm51",
            provider="zai-coding-plan",
            model_id="glm-5.1",
            sampling=SamplingDefaults(temperature=0.3),
        ),
        # Local vLLM Qwen3.5-27B served at http://localhost:8000/v1 —
        # registered as
        # `local-vllm-remote/qwen35-27b` in the user's global
        # ~/.config/opencode/opencode.json. Each candidate is invoked
        # against this model via the same opencode subprocess as the
        # z.ai variants, so the framework's mutator + evaluator code
        # path is identical regardless of where the model runs.
        "local": ModelPreset(
            name="local-qwen35",
            provider="local-vllm-remote",
            model_id="qwen35-27b",
            sampling=SamplingDefaults(temperature=0.6),
        ),
    },
    default_class="fast",
)


# Resolved fully-qualified model strings per class — the evaluator uses
# these to invoke each candidate against the right model.
CLASS_MODEL = {
    "fast": "zai-coding-plan/glm-4.5-air",
    "analytical": "zai-coding-plan/glm-5.1",
    "local": "local-vllm-remote/qwen35-27b",
}


CRITERION = OptimisationCriterion(
    name="full-explanations-per-model",
    aggregation="weighted",
    criteria=(
        Criterion.for_named(
            "response-min-length", "score_floor", target=1.0, weight=2.0,
        ),
        Criterion.for_named(
            "response-mentions-tradeoffs", "score_floor", target=1.0, weight=1.0,
        ),
    ),
)


TEST_PROMPTS = [
    "Explain the trade-off between consistency and availability in distributed systems.",
    "What is the difference between a process and a thread, and when would I pick each?",
]
