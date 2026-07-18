"""Agent + tool with embedded tests, exercised via `oac test`.

Demonstrates:
- CapabilityTest — pure introspection on compiled permissions; runs
  in milliseconds, no LLM, no I/O.
- ToolTest — exercise the tool's mock response, score with evaluators.
- A MockProfile registered on the registry so the tool test can bind
  a per-scenario mock without writing it inline.
- JSONL artifact emission to .oac/test_results.jsonl.
- Incremental skip via composite hash (re-running `oac test` skips
  passing tests whose state is unchanged).
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    BashToolPermission,
    CapabilityTest,
    CompilationConfig,
    EqualsEvaluator,
    JsonPathEvaluator,
    MockProfile,
    MockResponse,
    ModelParameters,
    PermissionAbsentEvaluator,
    SkillDefinition,
    TemplateSlot,
    TemplateTree,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolTest,
    WorkflowStep,
)


def echo_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo-tool",
            description="Returns the input text unchanged with metadata.",
            usage_explanation_long="Echo back the user's text + the run id.",
            usage_explanation_short="echo",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/echo.py *"],
            ),
            positive_examples=["uv run scripts/echo.py --text hi"],
            negative_examples=[], mode_specific_rules=[],
        ),
        mock=MockResponse(
            kind="fixed",
            fixed_output={"text": "DEFAULT-MOCK", "from": "tool.mock"},
        ),
        tool_tests=[
            ToolTest(
                name="echo-default-mock",
                input={"text": "anything"},
                evaluators=(
                    EqualsEvaluator(
                        field="from", expected="tool.mock",
                        name="reads_default_mock",
                    ),
                ),
            ),
            ToolTest(
                name="echo-via-mock-profile",
                input={"text": "anything"},
                mock_profile="ci",
                evaluators=(
                    JsonPathEvaluator(
                        path="from", expected="profile.ci",
                        name="reads_profile_mock",
                    ),
                ),
            ),
        ],
    )


def echo_skill() -> SkillDefinition:
    return SkillDefinition(
        name="echo-skill",
        description="Wraps the echo tool.",
        usage_explanation_long="Call echo-tool whenever the user asks for an echo.",
        usage_explanation_short="echo skill",
        rules=[],
        workflow_steps=[
            WorkflowStep(
                header="invoke echo", condition=None, result=None,
                rule="call once with the user's text", tools_used=[echo_tool()],
            ),
        ],
        positive_examples=[],
        negative_examples=[],
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="echo-agent",
            name="echo-agent",
            description="Echoes user text via a deterministic tool.",
        ),
        usage_explanation_long="Always call echo-tool; return its text field.",
        usage_explanation_short="echo agent",
        skills=[echo_skill()],
        system_prompt="Call echo-tool with the user's text. Return its `text` field.",
        # CapabilityTests run as pure introspection over the compiled
        # permission YAML — no LLM, no I/O.
        capability_tests=[
            CapabilityTest(
                name="echo-bash-allowed",
                must_have_bash_patterns=("uv run scripts/echo.py *",),
            ),
            CapabilityTest(
                name="echo-skill-allowed",
                must_have_skills=("echo-skill",),
            ),
            CapabilityTest(
                name="dangerous-bash-denied",
                evaluators=(
                    PermissionAbsentEvaluator(
                        permission_key="bash", bash_pattern="rm -rf *",
                        name="no_rm_rf",
                    ),
                ),
            ),
            CapabilityTest(
                name="write-permission-off-by-default",
                evaluators=(
                    PermissionAbsentEvaluator(permission_key="write"),
                ),
            ),
        ],
    )

    agent_id = reg.register_agent(
        "echo-agent", agent,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
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

    # MockProfile overrides the per-tool default — its 'echo-tool' entry
    # is what ToolTest(mock_profile='ci') binds against.
    reg.register_mock_profile(MockProfile(
        name="ci",
        responses={
            "echo-tool": MockResponse(
                kind="fixed",
                fixed_output={"text": "CI-MOCK", "from": "profile.ci"},
            ),
        },
    ))

    return reg
