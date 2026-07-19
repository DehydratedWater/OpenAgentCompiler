"""One agent tree, defined ONCE — adapted per (harness × model) target.

Three connected agents:
- `orchestrator` — routes every request through summarizer then critic.
- `summarizer` (model_class "fast") — compresses input.
- `critic` (model_class "analytical") — argues the other side.

`registry(target=...)` merges any promoted autoloop winner for that
target before registration (`apply_promoted_to_tree(target=...)`), so
the SAME definitions compile differently for opencode+fast, pi+smart,
or the interactive tier — each picking up its own tuned prompt, and
falling back per-class → default → the Python baseline when a target
was never tuned.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.improvement import apply_promoted_to_tree
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition

HERE = Path(__file__).resolve().parent


def _summarizer() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="summarizer", name="summarizer",
                           description="Compress text into one paragraph."),
        usage_explanation_long="Summarizes any input into one tight paragraph.",
        usage_explanation_short="summarizes",
        system_prompt="Summarize the input in one paragraph.",
        model_class="fast",
    )


def _critic() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="critic", name="critic",
                           description="Argue against the claim."),
        usage_explanation_long="Finds the strongest counter-arguments.",
        usage_explanation_short="critiques",
        system_prompt="List the strongest counter-arguments to the input.",
        model_class="analytical",
    )


def _orchestrator() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="orchestrator", name="orchestrator",
                           description="Summarize, then critique, then synthesize."),
        usage_explanation_long="Routes input through summarizer and critic.",
        usage_explanation_short="orchestrates",
        system_prompt="You coordinate two specialists and synthesize their outputs.",
        subagents=[
            AgentHeader(agent_id="summarizer", name="summarizer",
                        description="Compress text into one paragraph.",
                        mode="subagent"),
            AgentHeader(agent_id="critic", name="critic",
                        description="Argue against the claim.",
                        mode="subagent"),
        ],
        workflow=[
            WorkflowStepDefinition(
                id=1, name="Summarize",
                instructions="Spawn the summarizer on the raw input.",
                subagents=("summarizer",),
            ),
            WorkflowStepDefinition(
                id=2, name="Critique",
                instructions="Spawn the critic on the summary.",
                subagents=("critic",),
            ),
            WorkflowStepDefinition(
                id=3, name="Synthesize",
                instructions="Combine summary + critique into a balanced answer.",
            ),
        ],
        todo_mode="none",
    )


def registry(target: str | None = None) -> AgentRegistry:
    """Build the registry, merging promoted winners for `target`.

    `target` is a per-target loop key ("opencode+fast", "pi+analytical",
    "interactive") or None for the raw baseline. Resolution inside
    apply_promoted_to_tree is target → model_class → default, so a
    partially-tuned matrix still compiles everywhere.
    """
    reg = AgentRegistry()
    ids = {}
    for build in (_summarizer, _critic, _orchestrator):
        agent = build()
        agent = apply_promoted_to_tree(
            agent, project_root=HERE, target=target,
            model_class=agent.model_class,
        )
        ids[agent.header.agent_id] = reg.register_agent(
            agent.header.agent_id, agent,
            ModelParameters(model_name="zai-coding-plan/glm-4.5-air",
                            temperature=0.4),
        )
    reg.register_template(TemplateTree(
        name="matrix",
        slots=[
            TemplateSlot(name="primary", default_agent_id=ids["orchestrator"]),
            TemplateSlot(name="summarizer", default_agent_id=ids["summarizer"]),
            TemplateSlot(name="critic", default_agent_id=ids["critic"]),
        ],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="matrix"))
    return reg
