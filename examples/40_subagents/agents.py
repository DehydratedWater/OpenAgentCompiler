"""Orchestrator with two Task-tool subagents.

Exercises:
- An orchestrator (slot 'primary', mode='primary') that dispatches via
  the Task tool.
- Two subagents (slot 'summarizer' and 'critic', mode='subagent') each
  with their own focused system prompt.
- AgentDefinition.subagents wiring (AgentHeader references) so the
  compiled orchestrator's SECURITY POLICY block lists the allowed
  Task targets and the prompt includes "## Available Subagents".
- Different agents in the same tree backed by different ModelPresets.

OpenCode's Task tool spawns the named subagent as a sub-session that
shares the parent's context but runs under the subagent's prompt +
permissions. The orchestrator merges the children's outputs.
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    AgentToolPermissions,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
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
            " the user's claim. Delegate via the Task tool — never try"
            " to summarise or critique inline."
        ),
        usage_explanation_short="summarise + critique orchestrator",
        subagents=[summarizer_ref, critic_ref],
        # Task tool permission is set explicitly so the SECURITY POLICY
        # block + the compiled YAML reflect that this agent can spawn
        # subagents.
        tool_permissions=AgentToolPermissions(),
        system_prompt=(
            "You orchestrate two specialists.\n"
            "\n"
            "When the user sends a message:\n"
            "1. Invoke `summarizer` via the Task tool with the user's"
            " text as the prompt. Wait for its single-paragraph reply.\n"
            "2. Invoke `critic` via the Task tool with the user's main"
            " claim as the prompt. Wait for its 2-3 sentence reply.\n"
            "3. Produce a final response with TWO labelled sections:\n"
            "   `SUMMARY:` <the summarizer's output>\n"
            "   `COUNTERPOINT:` <the critic's output>\n"
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
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.2),
    )
    sum_id = reg.register_agent(
        "summarizer", _summarizer(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.4),
    )
    # Critic runs on the local vLLM Qwen3.5-27B — proves heterogeneous
    # Task-tool dispatch (z.ai orchestrator → local-vllm subagent).
    # opencode reads each subagent's `model` from its frontmatter, so a
    # mixed-provider tree compiles + runs unchanged.
    crit_id = reg.register_agent(
        "critic", _critic(),
        ModelParameters(model_name="local-vllm-remote/qwen35-27b", temperature=0.7),
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
