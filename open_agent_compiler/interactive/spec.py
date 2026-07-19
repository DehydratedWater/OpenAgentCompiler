"""InteractiveAgentSpec — the runtime-agnostic intermediate the interactive
bindings consume.

Derived from an `AgentDefinition` + a *live* provider profile (a
`VariantSpec`/`SplitProfile` whose presets point at the interactive provider,
e.g. a local OpenAI-compatible qwen). A binding (LangChain, raw SDK) turns
this spec into a streaming runnable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentVariant,
    ModelParameters,
)
from open_agent_compiler.model.core.model_preset import ModelPreset
from open_agent_compiler.model.core.tools_model import ToolDefinition
from open_agent_compiler.model.core.variant_spec import VariantSpec


class ToolSpec(BaseModel):
    """A tool exposed to the interactive agent, runtime-agnostically.

    `input_schema` is a JSON-schema-shaped dict the binding hands to the
    model for native tool-calling. It is best-effort here (name/description
    are always present); a binding may refine it by introspecting the
    underlying `ScriptTool`'s Pydantic input model.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    script_paths: list[str] = Field(default_factory=list)


class InteractiveAgentSpec(BaseModel):
    """Everything a binding needs to build a streaming interactive agent."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    model: ModelPreset
    system_prompt: str
    tools: tuple[ToolSpec, ...] = ()
    output_schema: dict[str, Any] | None = None

    # --- live-provider conveniences (read from the resolved preset) ------
    @property
    def model_id(self) -> str:
        """Bare model id for the live provider (OpenAI-compatible `model`)."""
        return self.model.model_id

    @property
    def provider(self) -> str:
        return self.model.provider

    @property
    def base_url(self) -> str | None:
        return self.model.provider_options.get("base_url")

    @property
    def api_key_env(self) -> str | None:
        return self.model.provider_options.get("api_key_env")

    @property
    def temperature(self) -> float | None:
        return self.model.sampling.temperature


# --- builder -----------------------------------------------------------

def _tool_script_paths(tool: ToolDefinition) -> list[str]:
    paths: list[str] = []
    logic = tool.json_tool
    scripts = logic.tool_scripts if (logic and logic.tool_scripts) else []
    for ts in scripts:
        for p in (ts.paths or []):
            paths.append(str(p))
        for sd in (ts.scripts or []):
            if sd.target_file_path:
                paths.append(str(sd.target_file_path))
    # de-dup, preserve order
    seen: set[str] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def _tool_to_spec(tool: ToolDefinition) -> ToolSpec:
    # Reuse the compiler's schema derivation (imports the ScriptTool and
    # reads its Pydantic Input model) so interactive bindings get REAL
    # native tool schemas, not a single free-text arg. Best-effort: an
    # unimportable script yields an empty schema and the bindings fall
    # back to the classic `input: str` contract.
    from open_agent_compiler.compiler.dialects.opencode.tool_schema import derive_json_schema

    return ToolSpec(
        name=tool.header.name,
        description=tool.header.description,
        input_schema=derive_json_schema(tool) or {},
        script_paths=_tool_script_paths(tool),
    )


def _collect_tools(agent: AgentDefinition) -> list[ToolDefinition]:
    """Every tool reachable from an agent: explicit extras + per-workflow-step
    tools. De-duplicated by tool name."""
    found: dict[str, ToolDefinition] = {}
    for t in agent.extra_tools:
        found.setdefault(t.header.name, t)
    for step in agent.workflow:
        for t in getattr(step, "tools_used", []) or []:
            found.setdefault(t.header.name, t)
    return list(found.values())


def build_interactive_spec(
    *,
    agent: AgentDefinition,
    live_profile: VariantSpec,
    output_schema: dict[str, Any] | None = None,
) -> InteractiveAgentSpec:
    """Build an InteractiveAgentSpec for `agent`, resolving its model through
    the *live* provider profile (so the interactive layer uses a different
    provider than the opencode worker compile)."""
    from open_agent_compiler.interactive.prompt import render_interactive_prompt

    variant = AgentVariant(
        agent_definition=agent,
        model_parameters=ModelParameters(model_name=""),
    )
    preset = live_profile.preset_for(variant)
    tools = tuple(_tool_to_spec(t) for t in _collect_tools(agent))
    return InteractiveAgentSpec(
        agent_id=agent.header.agent_id,
        model=preset,
        system_prompt=render_interactive_prompt(agent),
        tools=tools,
        output_schema=output_schema,
    )
