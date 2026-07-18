"""A deliberately-weak agent + a criterion that scores its responses.

Designed to be improvable: the seed prompt asks for terse one-word
answers when the user actually needs full explanations. The criterion
penalises short responses, so the improvement loop has a clear signal
to optimise against.

Target model: z.ai/glm-4.5-air (cheap, fast, easy to push around).
Optimiser model (used by the LLM mutator): z.ai/glm-5.1.
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    OptimisationCriterion,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.improvement import Criterion


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    weak_explainer = AgentDefinition(
        header=AgentHeader(
            agent_id="weak-explainer",
            name="weak-explainer",
            description="Explains software concepts in a single sentence.",
        ),
        usage_explanation_long=(
            "Reads a software-engineering question and replies with"
            " a short answer."
        ),
        usage_explanation_short="terse software explainer",
        # Deliberately weak: pushes the model toward one-line answers
        # when an explanation paragraph would be more useful.
        system_prompt=(
            "You are a quick assistant. Answer the user in one sentence."
            " Be brief."
        ),
    )

    agent_id = reg.register_agent(
        "weak-explainer",
        weak_explainer,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    )

    reg.register_template(
        TemplateTree(
            name="explainer-tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="explainer-tpl"),
    )

    return reg


# What the improvement loop is trying to optimise for.
#
# Criterion.for_named(name, ...) is the shorthand that wires the
# scope='by_name' + scope_value=name combo automatically. The evaluator
# in improve_run.py emits metrics keyed `score_floor:by_name:<name>`,
# which matches the metric_key for this scoped form. Without
# .for_named, a bare Criterion defaults to scope='any' and looks at
# the wrong metric key — yielding a flat 0.5 score for every candidate.
CRITERION = OptimisationCriterion(
    name="full-explanations",
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


# The test prompts the evaluator hits each candidate with.
TEST_PROMPTS = [
    "Explain the trade-off between consistency and availability in distributed systems.",
    "What is the difference between a process and a thread, and when would I pick each?",
]
