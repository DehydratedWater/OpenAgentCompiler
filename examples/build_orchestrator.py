"""Build an orchestrator agent with workflow steps, subagents, and tool examples."""

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
from open_agent_compiler.writers import OpenCodeWriter

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def main() -> None:
    # -- Tools with named examples --
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

    thought_transfer = (
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

    # -- Skills (grouping tools with usage instructions) --
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

    # -- Subagents --
    quick_ack = (
        SubagentBuilder()
        .name("persona/twily_quick_ack-glm-45-air")
        .description("Instant Natural Response + Routing")
        .notes(
            "Sends IMMEDIATE acknowledgment BEFORE everything else.\n"
            "Detects intent and recommends routing."
        )
        .build()
    )

    # -- Config --
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
        .subagent("persona/twily_quick_ack-glm-45-air")
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

    # -- Agent --
    agent_def = (
        AgentBuilder()
        .name("twily-orchestrator")
        .description("Primary orchestrator for Twily persona")
        .mode("primary")
        .agent_dir("persona")
        .config(config)
        .tool(timestamp)
        .skill(
            context_skill,
            instruction="Use when resolving context or transferring "
            "data between agents",
        )
        .subagent(quick_ack)
        .preamble("# Fren Orchestrator\n\nYou orchestrate Twily's persona.")
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

    # -- Compile & write --
    compiled = compile_agent(agent_def, target="opencode")

    writer = OpenCodeWriter(
        output_dir=BUILD_DIR,
        scripts_dir=SCRIPTS_DIR,
    )
    writer.write(compiled)

    # Print the generated system prompt for verification
    print("=== Generated System Prompt ===")
    print(compiled["agent"]["system_prompt"])
    print()

    # Print tool permissions
    print("=== Tool Permissions ===")
    for key, value in compiled["tool"].items():
        print(f"  {key}: {value}")
    print()

    # Print agent permissions
    if "permission" in compiled:
        print("=== Agent Permissions ===")
        for key, value in compiled["permission"].items():
            print(f"  {key}: {value}")

    print(f"\nBuild output written to {BUILD_DIR}")


if __name__ == "__main__":
    main()
