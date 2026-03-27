"""Build a full orchestrator + subagent setup into a single build directory.

Demonstrates:
- Primary orchestrator with todowrite-based workflow
- Subagent with subagent_todo.py-based workflow
- Shared tools, predefined skills, and bundled scripts
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler._types import (
    ActionDefinition,
    ModelConfig,
    ModelOptions,
    ProviderConfig,
    ProviderOptions,
)
from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    SubagentBuilder,
    ToolBuilder,
    WorkflowStepBuilder,
)
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.predefined import (
    agent_orchestration_skill,
    subagent_todo_skill,
)
from open_agent_compiler.writers import OpenCodeWriter

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


# ── Shared tools ─────────────────────────────────────────────────────────────


def _build_thought_transfer() -> object:
    return (
        ToolBuilder()
        .name("thought-transfer")
        .description("Read/write thought data between agents")
        .action(
            ActionDefinition(
                command_pattern="uv run scripts/thought_transfer.py *",
                description="Transfer thought data between agents",
                usage_example="uv run scripts/thought_transfer.py write resolved_context --stdin",  # noqa: E501
            )
        )
        .example(
            "write",
            "Save data for another agent",
            "uv run scripts/thought_transfer.py write resolved_context --stdin",
        )
        .example(
            "read",
            "Read data from another agent",
            "uv run scripts/thought_transfer.py read quick_ack",
        )
        .example(
            "peek",
            "Peek at data without consuming",
            "uv run scripts/thought_transfer.py peek resolved_context",
        )
        .build()
    )


# ── Subagent definition (full AgentDefinition with workflow) ─────────────────


def build_quick_ack_subagent(thought_transfer, config):
    """Build the quick-ack subagent with subagent_todo workflow."""

    step_1 = (
        WorkflowStepBuilder()
        .id("1")
        .name("Read Context")
        .todo("Read context", "Read resolved context from orchestrator")
        .use_tool("thought-transfer", "read")
        .instructions("Read the resolved_context from the orchestrator.")
        .mark_done("Read context")
        .build()
    )

    step_2 = (
        WorkflowStepBuilder()
        .id("2")
        .name("Generate Quick Response")
        .todo("Generate response", "Create immediate acknowledgment")
        .instructions(
            "Based on the context, generate a quick, natural acknowledgment.\n"
            "Keep it brief — this is meant to be an instant response."
        )
        .mark_done("Generate response")
        .build()
    )

    step_3 = (
        WorkflowStepBuilder()
        .id("3")
        .name("Determine Routing")
        .todo("Determine routing", "Decide where to route the request")
        .evaluate(
            "routing_recommendation",
            "What type of handling does this need?",
            "workflow",
            "quick_chat",
            "full_flow",
        )
        .instructions(
            "Analyze the user's message and context to determine routing.\n"
            "Consider: complexity, intent, whether it needs tools or just chat."
        )
        .mark_done("Determine routing")
        .build()
    )

    step_4 = (
        WorkflowStepBuilder()
        .id("4")
        .name("Write Results")
        .todo("Write results", "Save ack and routing decision for orchestrator")
        .use_tool("thought-transfer", "write")
        .instructions(
            "Write both the quick_ack response and routing_decision "
            "via thought-transfer for the orchestrator to consume."
        )
        .mark_done("Write results")
        .build()
    )

    return (
        AgentBuilder()
        .name("quick-ack-subagent")
        .description("Instant Natural Response + Routing")
        .mode("subagent")
        .agent_dir("persona")
        .config(config)
        .tool(thought_transfer)
        .skill(
            subagent_todo_skill(),
            instruction="Use for mandatory progress tracking in every run",
        )
        .preamble(
            "# Quick Ack Subagent\n\n"
            "You provide instant acknowledgment and routing recommendations.\n"
            "You are a subagent — you CANNOT use todoread/todowrite tools.\n"
            "Use `subagent_todo.py` for progress tracking instead."
        )
        .workflow_step(step_1)
        .workflow_step(step_2)
        .workflow_step(step_3)
        .workflow_step(step_4)
        .postamble(
            "## Important Notes\n\n"
            "- Keep responses SHORT and natural\n"
            "- Always write your routing decision before finishing"
        )
        .build()
    )


# ── Orchestrator definition (primary with todowrite workflow) ────────────────


def build_orchestrator(thought_transfer, config):
    """Build the primary orchestrator agent."""

    context_resolver = (
        ToolBuilder()
        .name("context-resolver")
        .description("Resolve context references from conversation history")
        .action(
            ActionDefinition(
                command_pattern="uv run scripts/context_resolver.py *",
                description="Resolve context references",
                usage_example='uv run scripts/context_resolver.py resolve "{user_message}"',  # noqa: E501
            )
        )
        .example(
            "resolve",
            "Resolve references from conversation",
            'uv run scripts/context_resolver.py resolve "{user_message}"',
        )
        .example(
            "lookup",
            "Look up a specific topic",
            'uv run scripts/context_resolver.py lookup --topic "{topic}"',
        )
        .build()
    )

    timestamp = (
        ToolBuilder()
        .name("timestamp")
        .description("Get current timestamp")
        .action(
            ActionDefinition(
                command_pattern="date *",
                description="Get current timestamp",
                usage_example="date +%s",
            )
        )
        .example("now", "Get current epoch timestamp", "date +%s")
        .build()
    )

    context_skill = (
        SkillBuilder()
        .name("context-tools")
        .description("Context resolution and thought transfer")
        .instructions(
            "Use context-resolver to resolve references like "
            "'this', 'that', 'it' from conversation history.\n"
            "Use thought-transfer to pass resolved data between "
            "agents in the orchestration pipeline."
        )
        .tool(context_resolver)
        .tool(thought_transfer)
        .build()
    )

    quick_ack_ref = (
        SubagentBuilder()
        .name("persona/quick-ack-subagent")
        .description("Instant Natural Response + Routing")
        .notes(
            "Sends IMMEDIATE acknowledgment BEFORE everything else.\n"
            "Detects intent and recommends routing."
        )
        .build()
    )

    # -- Workflow steps --
    step_1 = (
        WorkflowStepBuilder()
        .id("1")
        .name("Record Start Time")
        .todo("Record timestamp", "Get start time for new message check")
        .use_tool("timestamp")
        .instructions("Get the current timestamp and save it.")
        .build()
    )

    step_1_5 = (
        WorkflowStepBuilder()
        .id("1.5")
        .name("Resolve Context")
        .todo("Resolve context", "Resolve references like 'this', 'that'")
        .use_tool("context-resolver", "resolve")
        .use_tool("thought-transfer", "write")
        .instructions("Run the context resolver, then save the output.")
        .build()
    )

    step_2 = (
        WorkflowStepBuilder()
        .id("2")
        .name("Quick Acknowledgment")
        .todo("Send quick ack", "Immediate feedback + routing decision")
        .subagent("persona/quick-ack-subagent")
        .use_tool("thought-transfer", "peek")
        .instructions("Use Task tool to invoke the quick_ack subagent.")
        .build()
    )

    step_2_1 = (
        WorkflowStepBuilder()
        .id("2.1")
        .name("Read Routing Decision")
        .todo("Read routing decision", "Determine which path to take")
        .use_tool("thought-transfer", "read")
        .evaluate(
            "routing_recommendation",
            "What did quick_ack recommend?",
            "workflow",
            "quick_chat",
            "full_flow",
        )
        .evaluate(
            "has_image",
            "Does the user message contain an image?",
            "true",
            "false",
        )
        .route("routing_recommendation", "workflow", goto="2.2")
        .route("routing_recommendation", "quick_chat", goto="5.5")
        .route("routing_recommendation", "full_flow", goto="2.5")
        .mark_done("Read routing decision")
        .instructions("Read the quick_ack output and parse routing fields.")
        .build()
    )

    step_2_2 = (
        WorkflowStepBuilder()
        .id("2.2")
        .name("Workflow Delegation")
        .todo(
            "Route to handler",
            "Execute appropriate handler based on route",
        )
        .gate("routing_recommendation", "workflow")
        .use_tool("thought-transfer", "read")
        .instructions("Invoke the appropriate workflow agent.")
        .build()
    )

    step_2_5 = (
        WorkflowStepBuilder()
        .id("2.5")
        .name("Analyze Image")
        .gate("routing_recommendation", "full_flow")
        .gate("has_image", "true")
        .instructions("Invoke image processor subagent.")
        .build()
    )

    return (
        AgentBuilder()
        .name("example-orchestrator")
        .description("Primary orchestrator for Example persona")
        .mode("primary")
        .agent_dir("persona")
        .config(config)
        .tool(timestamp)
        .skill(
            context_skill,
            instruction="Use when resolving context or transferring "
            "data between agents",
        )
        .skill(
            agent_orchestration_skill(),
            instruction="Use when delegating work to other primary agents",
        )
        .subagent(quick_ack_ref)
        .preamble("# Fren Orchestrator\n\nYou orchestrate Example's persona.")
        .workflow_step(step_1)
        .workflow_step(step_1_5)
        .workflow_step(step_2)
        .workflow_step(step_2_1)
        .workflow_step(step_2_2)
        .workflow_step(step_2_5)
        .postamble(
            "## Error Handling\n\nIf a subagent fails, log the error and continue."
        )
        .build()
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def _print_compiled(label: str, compiled: dict) -> None:
    print(f"{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    print()
    print("--- System Prompt ---")
    print(compiled["agent"]["system_prompt"])
    print()
    print("--- Tool Permissions ---")
    for key, value in compiled["tool"].items():
        print(f"  {key}: {value}")
    if "permission" in compiled:
        print()
        print("--- Agent Permissions ---")
        for key, value in compiled["permission"].items():
            print(f"  {key}: {value}")
    print()


def main() -> None:
    # Shared config
    config = (
        ConfigBuilder()
        .provider(
            ProviderConfig(
                name="anthropic",
                options=ProviderOptions(api_key="env:ANTHROPIC_API_KEY"),
                models=(
                    ModelConfig(
                        name="sonnet",
                        id="claude-sonnet-4-5-20250929",
                        options=ModelOptions(temperature=0.0),
                    ),
                ),
            )
        )
        .default_model("anthropic/sonnet")
        .compaction(auto=True, prune=True)
        .build()
    )

    # Shared tool
    thought_transfer = _build_thought_transfer()

    # Build both agents
    orchestrator_def = build_orchestrator(thought_transfer, config)
    subagent_def = build_quick_ack_subagent(thought_transfer, config)

    # Compile both
    orchestrator_compiled = compile_agent(orchestrator_def, target="opencode")
    subagent_compiled = compile_agent(subagent_def, target="opencode")

    # Write both to same build directory
    writer = OpenCodeWriter(output_dir=BUILD_DIR, scripts_dir=SCRIPTS_DIR)
    writer.write(orchestrator_compiled)
    writer.write(subagent_compiled)

    # Print results
    _print_compiled(
        "ORCHESTRATOR (primary — todowrite workflow)", orchestrator_compiled
    )
    _print_compiled("SUBAGENT (subagent — subagent_todo workflow)", subagent_compiled)

    print(f"Build output written to {BUILD_DIR}")


if __name__ == "__main__":
    main()
