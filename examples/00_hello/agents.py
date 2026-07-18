"""Minimal hello agent — one-shot greeter backed by z.ai glm-4.5-air."""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    greeter = AgentDefinition(
        header=AgentHeader(
            agent_id="hello-greeter",
            name="hello-greeter",
            description="Says hello back with a warm one-line greeting.",
        ),
        usage_explanation_long=(
            "A minimal agent useful for end-to-end framework smoke tests."
            " Responds to any message with a single friendly sentence."
            " If the user mentions their name, use it."
        ),
        usage_explanation_short="warm greeting in one sentence",
        system_prompt=(
            "You are a friendly greeter. Reply with exactly one short,"
            " warm sentence. If the user mentioned their name, use it."
            " Do not ask follow-up questions."
        ),
    )

    agent_id = reg.register_agent(
        "hello-greeter",
        greeter,
        ModelParameters(
            model_name="zai-coding-plan/glm-4.5-air",
            temperature=0.7,
        ),
    )

    reg.register_template(
        TemplateTree(
            name="hello-tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )

    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="hello-tpl"),
    )

    return reg


if __name__ == "__main__":
    r = registry()
    print(f"agents: {r.list_agents()}")
    print(f"configs: {r.list_configs()}")
