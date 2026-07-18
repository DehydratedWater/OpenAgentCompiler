"""Time-aware assistant with bash + JSON-schema tool variants.

Demonstrates:
- ScriptTool wired into a ToolDefinition with both bash_tool and
  json_tool contracts (real opencode setups choose one per agent).
- An agent that uses tool_format='both' so the compiled artifact
  carries both the bash allowlist + the custom_tools block — useful
  for cross-runtime portability.
- A second agent with tool_format='json' only — shows the structured
  JSON-schema tool emission path.
- MockableTool default (ToolDefinition.mock) so AgentTests can run
  with deterministic outputs.
- AccessProfile declaring the tool needs no external resources.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler import (
    AccessProfile,
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    BashToolPermission,
    CompilationConfig,
    JsonToolPermission,
    ModelParameters,
    MockResponse,
    ResourceBinding,
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


def time_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="time-tool",
            description="Return current UTC time (optional timezone offset).",
            usage_explanation_long=(
                "Use when the user asks for the current time, the time in"
                " a specific timezone, or anything date-relative. Pass an"
                " integer hour offset via --timezone_hours (e.g. 1=CET,"
                " -8=PST)."
            ),
            usage_explanation_short="get the current time",
            rules=[
                "Always include a timezone in the answer.",
                "When the user asks 'what time is it' with no zone,"
                " default to UTC (timezone_hours=0).",
            ],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/time_tool.py *"],
            ),
            positive_examples=[
                "uv run scripts/time_tool.py --timezone_hours 0",
                "uv run scripts/time_tool.py --timezone_hours 1",
            ],
            negative_examples=[
                "date",  # never use the shell builtin
                "python -c \"import datetime; print(datetime.datetime.now())\"",
            ],
            mode_specific_rules=[
                "Always use `uv run` to launch the script.",
            ],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(
                tool_name="custom_tool", value="allow",
            ),
            positive_examples=[
                "time-tool(timezone_hours=0)",
                "time-tool(timezone_hours=-5)",
            ],
            negative_examples=[
                "time-tool(timezone='UTC')",  # wrong field name/type
            ],
            mode_specific_rules=[
                "Pass an integer for timezone_hours, never a string.",
            ],
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
        # Default mock so AgentTests / oac test runs against this tool
        # are deterministic without invoking the real handler.
        mock=MockResponse(
            kind="fixed",
            fixed_output={
                "iso": "2026-05-17T12:00:00+00:00",
                "timezone_hours": 0,
                "note": "mock",
            },
        ),
        requires_resources=[],  # no external systems
    )


def time_skill() -> SkillDefinition:
    return SkillDefinition(
        name="time-awareness",
        description="Pulls the current time from a deterministic script.",
        usage_explanation_long=(
            "Wrap the time-tool. When the user asks anything time-related,"
            " call the tool and incorporate its `iso` field into the answer."
        ),
        usage_explanation_short="time queries",
        rules=[
            "Always cite the timezone returned by the tool.",
            "Never invent a time; always call the tool.",
        ],
        workflow_steps=[
            WorkflowStep(
                header="Resolve the requested timezone",
                condition=None,
                result="timezone_hours integer ready",
                rule="Default to 0 (UTC) if the user didn't specify.",
                tools_used=[],
            ),
            WorkflowStep(
                header="Call the time tool",
                condition=None,
                result="ISO timestamp returned",
                rule="Pass timezone_hours and read the iso field.",
                tools_used=[time_tool()],
            ),
        ],
        positive_examples=[],
        negative_examples=[],
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    # Agent A: tool_format='both' — bash allowlist AND custom_tools block emit.
    # Agent B: tool_format='json' — only custom_tools block emits (no bash perm).
    agent_a = AgentDefinition(
        header=AgentHeader(
            agent_id="time-assistant-both",
            name="time-assistant-both",
            description="Knows the time. Bash + JSON-schema tool emission.",
        ),
        usage_explanation_long="Answers time-related questions using time-tool.",
        usage_explanation_short="time helper (bash+json)",
        system_prompt=(
            "You answer time-related questions by calling the time-tool"
            " and citing the returned ISO timestamp + timezone. Never"
            " invent a time."
        ),
        skills=[time_skill()],
        default_tool_format="both",
    )
    agent_b = AgentDefinition(
        header=AgentHeader(
            agent_id="time-assistant-json",
            name="time-assistant-json",
            description="Same agent, JSON-schema-only tool surface.",
        ),
        usage_explanation_long="Answers time-related questions; JSON tool only.",
        usage_explanation_short="time helper (json)",
        system_prompt=(
            "You answer time-related questions by calling the time-tool"
            " with the typed JSON form and citing the result."
        ),
        skills=[time_skill()],
        default_tool_format="json",
    )

    a_id = reg.register_agent(
        "time-both", agent_a,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )
    b_id = reg.register_agent(
        "time-json", agent_b,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=a_id),
                TemplateSlot(name="json-variant", default_agent_id=b_id),
            ],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )

    # No-op AccessProfile — the time tool needs no external resources.
    # Real projects' DB/API tools would bind here.
    return reg


PROFILES = [
    AccessProfile(name="prod", bindings={}),
    AccessProfile(name="ci", bindings={
        "fake": ResourceBinding(kind="other", config={}, mock_only=True),
    }),
]
