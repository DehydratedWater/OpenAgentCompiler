"""Same agent compiled three ways: z.ai default, z.ai glm-5.1, local vLLM Qwen.

Demonstrates VariantSpec — a single agent definition fans out into
side-by-side per-provider artifacts under the same target tree. Each
gets its own .opencode/agents/<slot><postfix>.md and its own model in
the frontmatter; the user picks at invocation time via
`opencode run --agent primary[-glm51|-qwen]`.
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    ModelPreset,
    SamplingDefaults,
    TemplateSlot,
    TemplateTree,
    VariantSpec,
)


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    summariser = AgentDefinition(
        header=AgentHeader(
            agent_id="multi-summariser",
            name="multi-summariser",
            description="Summarises arbitrary user-supplied text in one paragraph.",
        ),
        usage_explanation_long=(
            "Reads whatever the user sends and returns a single dense"
            " paragraph capturing the key points. No bullet lists, no"
            " preamble — just the summary."
        ),
        usage_explanation_short="one-paragraph summary",
        system_prompt=(
            "You are a concise summariser. Read the user's message and"
            " reply with exactly one paragraph (3-5 sentences) capturing"
            " the key points. Do NOT use bullet lists, do NOT add"
            " preamble. Start the summary directly."
        ),
    )

    # Baseline registration — variants override the preset per compile pass.
    agent_id = reg.register_agent(
        "multi-summariser",
        summariser,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.5),
    )

    reg.register_template(
        TemplateTree(
            name="summariser-tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="summariser-tpl"),
    )
    return reg


# Three variants — used by build_agents.py and the test suite.
VARIANTS: list[VariantSpec] = [
    VariantSpec(
        name="default",
        postfix="",
        preset=ModelPreset(
            name="zai-glm-45-air",
            provider="zai-coding-plan",
            model_id="glm-4.5-air",
            sampling=SamplingDefaults(temperature=0.5),
        ),
    ),
    VariantSpec(
        name="glm51",
        postfix="-glm51",
        preset=ModelPreset(
            name="zai-glm-51",
            provider="zai-coding-plan",
            model_id="glm-5.1",
            sampling=SamplingDefaults(temperature=0.5),
        ),
    ),
    VariantSpec(
        name="qwen",
        postfix="-qwen",
        preset=ModelPreset(
            name="vllm-qwen35-27b",
            provider="local-vllm-remote",
            model_id="qwen35-27b",
            sampling=SamplingDefaults(temperature=0.6),
        ),
    ),
]


if __name__ == "__main__":
    r = registry()
    print(f"agents: {r.list_agents()}")
    print(f"variants: {[v.name for v in VARIANTS]}")
