"""getting-started skill — the canonical entry point for a coding agent."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle


BODY = """\
# Getting started with open-agent-compiler

This project was scaffolded by `oac init`. Your job, as a coding agent
working in this repo, is to use the framework to build and ship agents
that satisfy the user's goals.

## The three commands you'll use most

```bash
# 1. Compile every registered agent into ./build/.opencode/
uv run python build_agents.py

# 2. List what got registered without compiling
uv run oac info agents:registry

# 3. Run the embedded tests
uv run oac test agents:registry --config prod
```

`build_agents.py` targets opencode by default. The same registry compiles
for other runtimes via the dialect flag — `uv run oac compile
agents:registry --config prod --target build --dialect claude` (or `pi`);
list registered dialects with `uv run oac info --dialects`. For the
in-process streaming tier (LangChain), see the `interactive-agents` skill.

## The shape of an agent definition

Agents live in `agents/`. The conventional entry point is
`agents.registry:registry`, a no-arg callable that returns an
`AgentRegistry`. The CLI commands all resolve this entry by default.

```python
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry,
    CompilationConfig, ModelParameters,
    TemplateSlot, TemplateTree,
)

def registry() -> AgentRegistry:
    reg = AgentRegistry()

    my_agent = AgentDefinition(
        header=AgentHeader(agent_id="my-agent",
                           name="my-agent",
                           description="One-liner that says what it does."),
        usage_explanation_long="What the agent is for, in 1–3 paragraphs.",
        usage_explanation_short="terse summary",
        system_prompt="You are a … agent.",
    )
    agent_id = reg.register_agent(
        "my-agent", my_agent,
        ModelParameters(model_name="claude-sonnet-4-5", temperature=0.7),
    )
    reg.register_template(TemplateTree(
        name="default",
        slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="default"),
    )
    return reg
```

## Workflow guidance for the coding agent

1. **Never modify `build/` directly** — it's generated. Edit the
   source in `agents/` and recompile.
2. **Add new dependencies** with `uv add <pkg>` (writes to pyproject).
3. **When something fails to compile**, run `uv run oac info
   agents:registry` first to see what's registered; the error usually
   points at the agent_id, slot, or config name that's misspelled.
4. **For docker problems**, see the `docker-and-compose` skill.
5. **When the user asks you to add a tool or test**, see the
   `authoring-tools` and `writing-tests` skills.

## Where to learn the rest

The skills installed alongside this one cover every other topic:

- `authoring-agents` — how to design an agent properly
- `authoring-tools` — ScriptTool, MockableTool, AccessProfile
- `writing-tests` — CapabilityTest, ToolTest, JSONL artifacts
- `providers-and-models` — wiring different LLM providers + per-agent presets
- `docker-and-compose` — the scaffolded Docker setup and common fixes
- `variants-and-profiles` — multi-variant compilation, SplitProfile
- `improvement-loop` — `oac improve` (when Phase 6 lands)
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="getting-started",
        description=(
            "Canonical entry point. The three commands you'll use most, agent"
            " definition shape, where to find every other skill."
        ),
        body_markdown=BODY,
        tools_hint=("uv", "oac", "git"),
    )
