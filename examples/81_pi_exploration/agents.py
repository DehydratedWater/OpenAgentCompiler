"""Pi exploration agent example — uses pi's Explore subagent type.

Demonstrates:
- An orchestrator that delegates codebase exploration to pi's built-in Explore agent
- Using pi's `Agent()` tool with subagent_type="Explore"
- Read-only exploration pattern (Explore agent only gets read/grep/find/ls tools)
- Compiling for pi runtime with dialect="pi"

Pi's built-in Explore agent is optimized for fast codebase navigation:
- Uses haiku model by default (fast and cheap)
- Read-only tools (read, grep, find, ls)
- Standalone prompt (doesn't inherit parent's full context)

See: https://pi.dev/packages/@tintinweb/pi-subagents
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
    WorkflowStepDefinition,
)


def _explorer_orchestrator() -> AgentDefinition:
    """Orchestrator that delegates exploration to pi's Explore agent."""
    return AgentDefinition(
        header=AgentHeader(
            agent_id="explorer-orch",
            name="explorer-orchestrator",
            description="Explores codebases by delegating to pi's Explore agent.",
        ),
        usage_explanation_long=(
            "Receives a question about a codebase and delegates exploration"
            " to pi's built-in Explore agent. Synthesizes the findings into"
            " a clear answer."
        ),
        usage_explanation_short="codebase explorer",
        workflow=[
            WorkflowStepDefinition(
                id=1,
                name="ExploreCodebase",
                instructions=(
                    "Spawn pi's Explore agent to investigate the user's question."
                    " Provide a clear, specific prompt describing what to look for."
                ),
                # Note: We reference "Explore" (pi's built-in type) not a custom agent
                # In a real deployment, you'd reference custom subagents defined in
                # your agent tree. This example shows the pattern.
            ),
            WorkflowStepDefinition(
                id=2,
                name="SynthesizeFindings",
                instructions=(
                    "Review the Explore agent's findings and synthesize them into"
                    " a clear, structured answer for the user."
                ),
            ),
        ],
        system_prompt=(
            "You explore codebases by delegating to pi's Explore agent.\n"
            "\n"
            "When the user asks a question about the codebase:\n"
            "1. Spawn the Explore agent with a specific prompt\n"
            "2. Wait for its findings\n"
            "3. Synthesize the findings into a clear answer\n"
            "\n"
            "Don't try to explore the codebase yourself — delegate to Explore.\n"
            "Your value is in asking good questions and synthesizing results.\n"
            "\n"
            "To spawn Explore:\n"
            "`Agent({ subagent_type: \"Explore\", prompt: \"<specific question>\", description: \"Explore codebase\" })`"
        ),
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    orch_id = reg.register_agent(
        "explorer-orch", _explorer_orchestrator(),
        ModelParameters(model_name="anthropic/claude-sonnet-4-20250514", temperature=0.2),
    )

    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=orch_id),
            ],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


if __name__ == "__main__":
    r = registry()
    print(f"agents: {r.list_agents()}")
