"""Multi-turn AgentTest + sequenced mocks — Phase 11 patterns.

A monitoring agent that:
  - Turn 1: checks for new alerts (mocked stream)
  - Turn 2: receives a new alert in the stream
  - Turn 3: the stream goes quiet — agent should report no new alerts

The tool's mock is `sequence`: each call returns the next batch,
emulating a stateful data source without requiring real wire I/O.
A second tool uses `stateful_callable` to remember "last seen
timestamp" across calls — exactly the shape a real monitoring
agent needs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_agent_compiler import (  # noqa: E402
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    AgentTest,
    BashToolPermission,
    CompilationConfig,
    JsonToolPermission,
    ModelParameters,
    MockProfile,
    MockResponse,
    ScriptDefinition,
    SubstringEvaluator,
    TemplateSlot,
    TemplateTree,
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
    ToolDefinitionLogicJson,
    ToolScriptDefinition,
    Turn,
)

HERE = Path(__file__).resolve().parent


# ---- The alert-stream tool. Real impl would tail a kafka topic /
# poll a webhook bus / read a database; the schema is the same. ----

def fetch_alerts_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="fetch-alerts",
            description="Fetch new alerts since the last check.",
            usage_explanation_long=(
                "Returns the list of alerts that arrived since the"
                " last successful call. Empty list = nothing new."
            ),
            usage_explanation_short="poll alerts",
            rules=["Treat an empty list as 'nothing new', not an error."],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/fetch_alerts.py *"],
            ),
            positive_examples=["uv run scripts/fetch_alerts.py"],
            negative_examples=[],
            mode_specific_rules=[],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(
                tool_name="custom_tool", value="allow",
            ),
            positive_examples=["fetch-alerts()"],
            negative_examples=[],
            mode_specific_rules=[],
            tool_scripts=[
                ToolScriptDefinition(
                    paths=[HERE / "scripts" / "fetch_alerts.py"],
                    scripts=[ScriptDefinition(
                        target_file_path=Path("scripts/fetch_alerts.py"),
                        source_file_path=HERE / "scripts" / "fetch_alerts.py",
                        source_file_type="python",
                        script_contents=None,
                    )],
                ),
            ],
        ),
    )


# ---- The monitoring agent itself ----


def monitor() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="alert-monitor", name="alert-monitor",
            description="Polls the alert stream and reports new entries.",
        ),
        usage_explanation_long=(
            "On each user message, the agent calls fetch-alerts and"
            " summarises whatever it returns. If empty, says 'no new alerts'."
        ),
        usage_explanation_short="alert poller",
        system_prompt=(
            "You are an alert monitor. On every user message:\n"
            "1. Call fetch-alerts.\n"
            "2. If the result is empty, reply 'No new alerts'.\n"
            "3. Otherwise, summarise each alert in one bullet."
        ),
        extra_tools=[fetch_alerts_tool()],
        # Phase 11: multi-turn test exercising a sequenced mock.
        agent_tests=[
            AgentTest(
                name="monitor-three-checks",
                turns=(
                    Turn(prompt="check now",
                         expected_tool_calls=("fetch-alerts",),
                         evaluators=(SubstringEvaluator(needle="No new alerts"),)),
                    Turn(prompt="check again",
                         expected_tool_calls=("fetch-alerts",),
                         evaluators=(SubstringEvaluator(needle="ALERT-001"),)),
                    Turn(prompt="anything now?",
                         expected_tool_calls=("fetch-alerts",),
                         evaluators=(SubstringEvaluator(needle="No new alerts"),)),
                ),
                access_profile="prod",
                mock_profile="stream-mocks",
            ),
        ],
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent_id = reg.register_agent(
        "alert-monitor", monitor(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )

    # Phase 11: sequenced mock — three calls produce three distinct outputs.
    # Out-of-bounds (4th, 5th, …) reuses the final element so a long
    # session terminates cleanly with the 'empty' steady state.
    reg.register_mock_profile(MockProfile(
        name="stream-mocks",
        responses={
            "fetch-alerts": MockResponse(
                kind="sequence",
                sequence=(
                    MockResponse(kind="fixed", fixed_output={"alerts": []}),
                    MockResponse(kind="fixed", fixed_output={
                        "alerts": [
                            {"id": "ALERT-001", "severity": "warn",
                             "text": "disk usage 85% on db-1"},
                        ],
                    }),
                    MockResponse(kind="fixed", fixed_output={"alerts": []}),
                ),
            ),
        },
    ))

    reg.register_template(TemplateTree(
        name="tpl",
        slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


def print_test_summary() -> None:
    reg = registry()
    variant = reg.get_agent(reg.list_agents()[0])
    test = variant.agent_definition.agent_tests[0]
    print(f"AgentTest: {test.name!r} (multi_turn={test.is_multi_turn})")
    print(f"  turns: {len(test.turns)}")
    for i, turn in enumerate(test.turns, start=1):
        print(f"  turn {i}: prompt={turn.prompt!r}")
        print(f"    expected_tool_calls: {turn.expected_tool_calls}")
        if turn.evaluators:
            ev = turn.evaluators[0]
            print(f"    evaluator: {type(ev).__name__}(needle={ev.needle!r})")
    profile = reg.get_mock_profile("stream-mocks")
    seq_mock = profile.responses["fetch-alerts"]
    print("\nMock profile 'stream-mocks':")
    print(f"  fetch-alerts.kind = {seq_mock.kind}")
    print(f"  sequence length   = {len(seq_mock.sequence)}")
    for i, m in enumerate(seq_mock.sequence):
        print(f"    call {i}: {m.fixed_output}")


if __name__ == "__main__":
    print_test_summary()
