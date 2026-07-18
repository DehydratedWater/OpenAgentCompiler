"""Composable self-evolving components — agent + tool + skill, each
independently auto-iterated and reloaded.

This example demonstrates the vision laid out by the user:

  "Each part of this composable structure can be replaced with an
   auto-optimised version of itself, based on defined tests and
   iterated loops. The user still operates on a composable structure
   — but each piece transparently loads its improved twin when one
   has been promoted, and the baseline when one hasn't."

The agent below has three improvable pieces:

  1. The agent's own `system_prompt`.
  2. A `time-tool` ToolDefinition (header description / rules).
  3. A `time-awareness` SkillDefinition (description / rules).

Each piece has its own `component_id` and can be improved + promoted
*independently*. The `registry()` function below calls
`register_with_improvements()` which walks the tree once and merges
any promoted snapshots onto the baseline. Components without a
promoted snapshot pass through unchanged. The composition is
preserved either way.

The companion `seed_improvements.py` script populates
`.oac/promoted/` with three independent example snapshots so you can
see the wiring without having to actually run a 30-minute
optimization loop. Real users would promote real winners produced by
`oac improve`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running the file directly via `python agents.py` for a quick
# preview of the merged state. `build_agents.py` users won't hit this
# branch because the repo root is already on sys.path.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from open_agent_compiler import (  # noqa: E402
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    BashToolPermission,
    CompilationConfig,
    JsonToolPermission,
    ModelParameters,
    MockResponse,
    ScriptDefinition,
    SkillDefinition,
    TemplateSlot,
    TemplateTree,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
    ToolScriptDefinition,
    WorkflowStep,
)

HERE = Path(__file__).resolve().parent


def _time_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="time-tool",
            # Baseline description; improved version may rewrite this.
            description="Return current UTC time.",
            usage_explanation_long=(
                "Call when the user asks for the current time."
            ),
            usage_explanation_short="time lookup",
            # Baseline rules; improved version may rewrite these.
            rules=["Use UTC by default."],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/time_tool.py *"],
            ),
            positive_examples=["uv run scripts/time_tool.py --timezone_hours 0"],
            negative_examples=["date"],
            mode_specific_rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(
                tool_name="custom_tool", value="allow",
            ),
            positive_examples=["time-tool(timezone_hours=0)"],
            negative_examples=[],
            mode_specific_rules=[],
            tool_scripts=[
                ToolScriptDefinition(
                    paths=[HERE / "scripts" / "time_tool.py"],
                    scripts=[
                        ScriptDefinition(
                            target_file_path=Path("scripts/time_tool.py"),
                            source_file_path=HERE / "scripts" / "time_tool.py",
                            source_file_type="python",
                            script_contents=None,
                        ),
                    ],
                ),
            ],
        ),
        mock=MockResponse(
            kind="fixed",
            fixed_output={"iso": "2026-05-17T12:00:00+00:00",
                          "timezone_hours": 0, "note": "mock"},
        ),
        requires_resources=[],
    )


def _time_skill() -> SkillDefinition:
    return SkillDefinition(
        name="time-awareness",
        # Baseline description; improved version may rewrite this.
        description="Time skill — basic wrapper.",
        usage_explanation_long=(
            "Wrap the time-tool when the user asks anything time-related."
        ),
        usage_explanation_short="time queries",
        rules=["Always call the tool."],
        workflow_steps=[
            WorkflowStep(
                header="Call the time tool",
                condition=None,
                result="ISO timestamp returned",
                rule="Pass timezone_hours and read the iso field.",
                tools_used=[_time_tool()],
            ),
        ],
        positive_examples=[],
        negative_examples=[],
    )


def _baseline_agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="time-explainer",
            name="time-explainer",
            description=(
                "Composable time-aware agent — each part can be"
                " independently auto-improved."
            ),
        ),
        usage_explanation_long=(
            "Answers time-related questions using the time tool."
            " Each composable piece (agent prompt, tool, skill) can"
            " be promoted to its improved version independently."
        ),
        usage_explanation_short="composable time agent",
        # Baseline system prompt; improved version may rewrite this.
        system_prompt="You answer questions about time briefly.",
        skills=[_time_skill()],
        default_tool_format="both",
    )


def registry() -> AgentRegistry:
    """Build the registry, applying every promoted improvement transparently.

    register_with_improvements walks the AgentDefinition tree (agent
    itself + every skill + every extra_tool) and merges any
    promotions found under .oac/promoted/ — keyed by
    `header.agent_id` / `skill.name` / `tool.header.name`. Anything
    without a promoted snapshot stays at baseline.
    """
    reg = AgentRegistry()
    agent_id = reg.register_with_improvements(
        "time-explainer",
        _baseline_agent(),
        ModelParameters(
            model_name="zai-coding-plan/glm-4.5-air", temperature=0.3,
        ),
        project_root=HERE,
        # Use the agent's declared model_class; the resolver still
        # falls back to the default slot when no per-class snapshot
        # exists, so this is safe on partial promotions.
        model_class="default",
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


# Each composable piece's component_id — exported so seed_improvements.py
# (and any real `oac improve` runs) can target the same lookup keys.
COMPONENT_IDS = {
    "agent": "time-explainer",
    "tool": "time-tool",
    "skill": "time-awareness",
}


if __name__ == "__main__":
    # Quick visualisation: build the registry, print what each piece
    # currently is. Run seed_improvements.py first to populate
    # promotions; this script shows the merged state.
    reg = registry()
    agent_ids = reg.list_agents()
    if not agent_ids:
        print("registry is empty")
        raise SystemExit(0)
    variant = reg.get_agent(agent_ids[0])
    ad = variant.agent_definition
    print(f"agent system_prompt: {ad.system_prompt!r}")
    if ad.skills:
        s = ad.skills[0]
        print(f"skill[0].description: {s.description!r}")
        print(f"skill[0].rules:       {s.rules}")
    # Each tool surfaces through the skill's workflow step; walk and
    # print the embedded time-tool's effective header.
    for s in ad.skills:
        for step in s.workflow_steps:
            for tool in step.tools_used:
                print(f"tool {tool.header.name!r}:")
                print(f"  description: {tool.header.description!r}")
                print(f"  rules: {tool.header.rules}")
