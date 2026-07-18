"""Starter `agents/__init__.py` + `agents/registry.py` generators."""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_package_init(config: ScaffoldConfig) -> str:
    return (
        f'"""Agent definitions for {config.project_name}.\n\n'
        'A user-supplied factory must return an AgentRegistry; the CLI\n'
        '(oac compile / oac test / oac improve) looks for one at\n'
        f"`agents:registry` (i.e. {config.project_name}.agents.registry).\n"
        '"""\n\n'
        "from agents.registry import registry\n\n"
        '__all__ = ["registry"]\n'
    )


def render_registry(config: ScaffoldConfig) -> str:
    return (
        '"""Build and expose the AgentRegistry for this project."""\n'
        "\n"
        "from pathlib import Path\n"
        "\n"
        "from open_agent_compiler import (\n"
        "    AgentDefinition,\n"
        "    AgentHeader,\n"
        "    AgentRegistry,\n"
        "    CompilationConfig,\n"
        "    ModelParameters,\n"
        "    TemplateSlot,\n"
        "    TemplateTree,\n"
        ")\n"
        "\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
        "\n"
        "\n"
        "def _build() -> AgentRegistry:\n"
        "    reg = AgentRegistry()\n"
        "\n"
        "    starter = AgentDefinition(\n"
        '        header=AgentHeader(agent_id="starter", name="starter",\n'
        '                           description="A minimal starter agent."),\n'
        '        usage_explanation_long=(\n'
        '            "Greet the user warmly and explain what this agent does."\n'
        "        ),\n"
        '        usage_explanation_short="warm greeting + capability summary",\n'
        f'        system_prompt="You are a helpful agent in the {config.project_name}'
        ' project.",\n'
        "    )\n"
        "    # register_with_improvements auto-merges any promoted snapshot\n"
        "    # under .oac/promoted/ (Phase 10). On a fresh project this is\n"
        "    # a no-op; after `oac improve` + `oac promote`, the improved\n"
        "    # version of the agent ships transparently.\n"
        "    agent_id = reg.register_with_improvements(\n"
        '        "starter", starter,\n'
        f'        ModelParameters(model_name="{_default_model(config)}", temperature=0.7),\n'
        "        project_root=PROJECT_ROOT,\n"
        "    )\n"
        "    reg.register_template(\n"
        "        TemplateTree(\n"
        '            name="default",\n'
        "            slots=[\n"
        '                TemplateSlot(name="primary", default_agent_id=agent_id),\n'
        "            ],\n"
        "        )\n"
        "    )\n"
        "    reg.create_compilation_config(\n"
        '        CompilationConfig(name="prod", template_name="default"),\n'
        "    )\n"
        "    return reg\n"
        "\n"
        "\n"
        "# `oac compile / test / improve` resolve this attribute via\n"
        "# 'agents:registry'. Either expose the registry directly or wrap _build()\n"
        "# in a no-arg factory.\n"
        "def registry() -> AgentRegistry:\n"
        "    return _build()\n"
    )


def _default_model(config: ScaffoldConfig) -> str:
    """Return the provider-qualified model name (`provider/model_id`).

    Opencode requires the provider prefix to route the call; a bare
    'glm-4.5-air' fails resolution at run time. The scaffold writes
    the full qualified name so the generated registry.py works
    against the compiled tree without further user edits.
    """
    return {
        "anthropic": "anthropic/claude-sonnet-4-5-20250929",
        "openai": "openai/gpt-4o-mini",
        "openrouter": "openrouter/anthropic/claude-sonnet-4.5",
        "vllm": "vllm/meta-llama/Meta-Llama-3.1-8B-Instruct",
        "zai-coding-plan": "zai-coding-plan/glm-4.5-air",
    }[config.llm]


def render_build_agents_script(config: ScaffoldConfig) -> str:
    out_dir = {"opencode": ".opencode", "claude": ".claude", "pi": ".pi"}.get(
        config.dialect, config.dialect
    )
    return (
        f'"""Compile the registered agents into ./build/{out_dir}/."""\n'
        "\n"
        "from pathlib import Path\n"
        "\n"
        "from agents import registry\n"
        "from open_agent_compiler.compiler.script import CompileScript\n"
        "\n"
        "\n"
        "def main() -> None:\n"
        "    script = CompileScript(\n"
        '        target=Path("build"),\n'
        "        factory=registry,\n"
        '        config="prod",\n'
        f'        dialect="{config.dialect}",\n'
        "        clean=True,\n"
        "        verbose=True,\n"
        "    )\n"
        "    script.run()\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
