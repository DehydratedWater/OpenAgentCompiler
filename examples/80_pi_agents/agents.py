"""Pi agent example — orchestrator with two subagents compiled for pi runtime.

Demonstrates:
- An orchestrator (slot 'primary') that dispatches via the pi `Agent()` tool
- Two subagents (slot 'summarizer' and 'critic') each with focused prompts
- AgentDefinition.subagents wiring so the compiled orchestrator references
  the subagents in its prompt
- Different agents in the same tree backed by different models
- Skills and tools mapping to pi's frontmatter format

When compiled with `dialect="pi"`, this produces `.pi/agents/*.md` files
that pi-subagents can load and run.
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


def _summarizer() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="summarizer",
            name="summarizer",
            description="Compress text into one tight paragraph.",
        ),
        usage_explanation_long=(
            "Receives a text snippet from its parent and returns ONE"
            " paragraph (3-5 sentences) capturing the key points. No"
            " bullet lists, no preamble — just the summary."
        ),
        usage_explanation_short="one-paragraph summary",
        system_prompt=(
            "You are a concise summariser. Reply with exactly one"
            " paragraph (3-5 sentences). Start directly with the"
            " summary — no preamble, no apologies, no bullet lists."
        ),
    )


def _critic() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="critic",
            name="critic",
            description="Argue against the user's claim in 2-3 sentences.",
        ),
        usage_explanation_long=(
            "Reads a claim and returns 2-3 sentences naming the strongest"
            " counter-argument or hidden trade-off. Avoid hedging — pick"
            " the most pointed objection and state it clearly."
        ),
        usage_explanation_short="sharp counter-argument",
        system_prompt=(
            "You are a contrarian reviewer. Read the user's claim and"
            " respond with 2-3 sentences naming the single strongest"
            " counter-argument or hidden trade-off. Be pointed; avoid"
            " hedging language like 'it depends' or 'on the other hand'."
        ),
    )


def _orchestrator() -> AgentDefinition:
    summarizer_ref = AgentHeader(
        agent_id="summarizer", name="summarizer",
        description="Compress text into one paragraph.",
        mode="subagent",
    )
    critic_ref = AgentHeader(
        agent_id="critic", name="critic",
        description="Argue against the user's claim.",
        mode="subagent",
    )

    # Define a simple workflow for the orchestrator
    workflow = [
        WorkflowStepDefinition(
            id=1,
            name="SpawnSummarizer",
            instructions=(
                "Spawn the summarizer subagent with the user's text as the prompt."
                " Wait for its single-paragraph reply."
            ),
            subagents=("summarizer",),
        ),
        WorkflowStepDefinition(
            id=2,
            name="SpawnCritic",
            instructions=(
                "Spawn the critic subagent with the user's main claim as the prompt."
                " Wait for its 2-3 sentence reply."
            ),
            subagents=("critic",),
        ),
        WorkflowStepDefinition(
            id=3,
            name="AssembleResponse",
            instructions=(
                "Produce a final response with TWO labelled sections:"
                " `SUMMARY:` <the summarizer's output>"
                " `COUNTERPOINT:` <the critic's output>"
            ),
        ),
    ]

    return AgentDefinition(
        header=AgentHeader(
            agent_id="orchestrator",
            name="orchestrator",
            description="Routes user input through summarizer + critic.",
        ),
        usage_explanation_long=(
            "Takes a longer-form user message and produces a final"
            " answer that combines (a) a one-paragraph summary of any"
            " text in the message and (b) a sharp counter-argument to"
            " the user's claim. Delegate via the Agent() tool — never try"
            " to summarise or critique inline."
        ),
        usage_explanation_short="summarise + critique orchestrator",
        subagents=[summarizer_ref, critic_ref],
        workflow=workflow,
        system_prompt=(
            "You orchestrate two specialists.\n"
            "\n"
            "When the user sends a message, follow the workflow steps"
            " to delegate to summarizer and critic, then assemble the"
            " final response.\n"
            "\n"
            "Never produce summaries or critiques yourself — always"
            " delegate. Don't paraphrase the subagent outputs; quote"
            " them verbatim under their labels."
        ),
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    orch_id = reg.register_agent(
        "orchestrator", _orchestrator(),
        ModelParameters(model_name="anthropic/claude-sonnet-4-20250514", temperature=0.2),
    )
    sum_id = reg.register_agent(
        "summarizer", _summarizer(),
        ModelParameters(model_name="anthropic/claude-haiku-4-5-20251001", temperature=0.4),
    )
    crit_id = reg.register_agent(
        "critic", _critic(),
        ModelParameters(model_name="anthropic/claude-haiku-4-5-20251001", temperature=0.7),
    )

    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=orch_id),
                TemplateSlot(name="summarizer", default_agent_id=sum_id),
                TemplateSlot(name="critic", default_agent_id=crit_id),
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
