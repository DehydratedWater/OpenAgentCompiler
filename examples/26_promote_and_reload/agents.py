"""Registry that auto-applies a promoted prompt — the missing link.

Demonstrates the actual usage loop:

1. Define the baseline AgentDefinition with the weak prompt.
2. apply_promoted_to_agent() looks for `.oac/promoted/<component>.json`
   in the project root; if present, it merges the promoted fields
   (system_prompt etc.) onto the baseline.
3. The registry returns the (maybe-improved) variant.

On a fresh project, step 2 is a no-op and the baseline ships. After
`oac improve` + `oac promote`, step 2 swaps in the improved prompt
and the next compile + every test + every opencode invocation uses
the better version.

This is what makes the autoresearch loop closed-loop instead of
write-only.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.improvement import apply_promoted_to_agent

HERE = Path(__file__).resolve().parent


def _baseline_agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="reload-explainer",
            name="reload-explainer",
            description="Explains software concepts; auto-applies promoted improvements.",
        ),
        usage_explanation_long=(
            "Reads a software question and answers. On a fresh project the"
            " agent uses the (weak) baseline prompt. After `oac promote`"
            " drops a snapshot at .oac/promoted/reload-explainer.json,"
            " the next registry build picks it up automatically."
        ),
        usage_explanation_short="auto-promoted explainer",
        system_prompt=(
            "You are a quick assistant. Answer the user in one sentence."
            " Be brief."
        ),
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    # Pull the baseline, then ask the framework to merge any promoted
    # improvements (no-op on fresh projects).
    agent = apply_promoted_to_agent(
        _baseline_agent(),
        component_id="reload-explainer",
        project_root=HERE,
    )

    agent_id = reg.register_agent(
        "reload-explainer", agent,
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


TEST_PROMPT = (
    "Explain the trade-off between consistency and availability in"
    " distributed systems."
)


if __name__ == "__main__":
    agent = apply_promoted_to_agent(
        _baseline_agent(), "reload-explainer", project_root=HERE,
    )
    print(f"Current system_prompt:\n  {agent.system_prompt!r}")
