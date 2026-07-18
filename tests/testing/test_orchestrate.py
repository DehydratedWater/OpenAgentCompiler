"""End-to-end TestRun orchestration."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.cli.main import main as cli_main
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.mock_model import MockProfile, MockResponse
from open_agent_compiler.model.core.permissions_model import BashToolPermission
from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
from open_agent_compiler.model.core.test_model import (
    CapabilityTest,
    EqualsEvaluator,
    ToolTest,
)
from open_agent_compiler.model.core.tools_model import (
    ToolDefinition,
    ToolDefinitionHeader,
    ToolDefinitionLogicBash,
)
from open_agent_compiler.testing.orchestrate import TestRun


def _factory_with_tests():
    reg = AgentRegistry()
    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo", description="d", usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/echo.py *"],
            ),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        mock=MockResponse(kind="fixed", fixed_output={"text": "hi"}),
        tool_tests=[
            ToolTest(
                name="echo-returns-hi", input={"text": "anything"},
                evaluators=(EqualsEvaluator(expected={"text": "hi"}),),
            ),
        ],
    )
    skill = SkillDefinition(
        name="echo-skill", description="d",
        usage_explanation_long="l", usage_explanation_short="s",
        rules=[],
        workflow_steps=[
            WorkflowStep(
                header="step", condition=None, result=None, rule="r",
                tools_used=[tool],
            )
        ],
        positive_examples=[], negative_examples=[],
    )
    agent = AgentDefinition(
        header=AgentHeader(agent_id="x", name="orch", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        skills=[skill],
        capability_tests=[
            CapabilityTest(
                name="bash-echo-allowed",
                must_have_bash_patterns=("uv run scripts/echo.py *",),
            ),
            CapabilityTest(
                name="write-denied",
                must_not_have_tools=("write",),
            ),
        ],
    )
    agent_id = reg.register_agent(
        "orch", agent, ModelParameters(model_name="m", temperature=0.0)
    )
    reg.register_template(
        TemplateTree(
            name="t",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="t"))
    reg.register_mock_profile(MockProfile(name="ci", responses={}))
    return reg


def test_discover_finds_capability_and_tool_tests(tmp_path: Path) -> None:
    run = TestRun(
        factory=_factory_with_tests, config="prod",
        artifacts_path=tmp_path / "r.jsonl",
    )
    summary = run.run()
    # 2 capability + 1 tool = 3 discovered
    assert summary.discovered == 3
    assert summary.passed == 3
    assert summary.failed == 0


def test_jsonl_artifacts_written_for_each_test(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    TestRun(factory=_factory_with_tests, config="prod", artifacts_path=path).run()
    assert path.exists()
    records = [json.loads(line) for line in path.read_text().strip().splitlines()]
    names = {r["test_name"] for r in records}
    assert names == {"bash-echo-allowed", "write-denied", "echo-returns-hi"}
    kinds = {r["test_kind"] for r in records}
    assert kinds == {"capability", "tool"}


def test_incremental_skips_when_run_a_second_time(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    s1 = TestRun(factory=_factory_with_tests, config="prod", artifacts_path=path).run()
    assert s1.passed == 3 and s1.skipped == 0

    s2 = TestRun(factory=_factory_with_tests, config="prod", artifacts_path=path).run()
    assert s2.skipped == 3
    assert s2.passed == 0
    assert s2.failed == 0


def test_force_flag_bypasses_skip(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    TestRun(factory=_factory_with_tests, config="prod", artifacts_path=path).run()
    s = TestRun(
        factory=_factory_with_tests, config="prod",
        artifacts_path=path, force=True,
    ).run()
    assert s.skipped == 0
    assert s.passed == 3


def test_name_filter_subset(tmp_path: Path) -> None:
    s = TestRun(
        factory=_factory_with_tests, config="prod",
        artifacts_path=tmp_path / "r.jsonl",
        name_filter="echo",
    ).run()
    # "bash-echo-allowed" + "echo-returns-hi" — write-denied filtered out
    assert s.discovered == 2


def test_kind_filter_limits_to_capability(tmp_path: Path) -> None:
    s = TestRun(
        factory=_factory_with_tests, config="prod",
        artifacts_path=tmp_path / "r.jsonl",
        kind_filter="capability",
    ).run()
    assert s.discovered == 2


def test_cli_invocation_emits_summary(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    # Install factory at a known module attribute the CLI can resolve.
    import sys
    monkeypatch.setattr(
        sys.modules[__name__], "_cli_factory", _factory_with_tests, raising=False,
    )
    results = tmp_path / "r.jsonl"
    rc = cli_main([
        "test",
        f"{__name__}:_cli_factory",
        "--config", "prod",
        "--results", str(results),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed=3" in out
    assert "failed=0" in out


def test_failing_test_returns_non_zero_exit(
    tmp_path: Path, monkeypatch,
) -> None:
    def factory_with_failure():
        reg = AgentRegistry()
        agent = AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            capability_tests=[
                CapabilityTest(
                    name="impossible",
                    must_have_tools=("nonexistent-tool",),
                ),
            ],
        )
        agent_id = reg.register_agent(
            "o", agent, ModelParameters(model_name="m", temperature=0.0)
        )
        reg.register_template(
            TemplateTree(
                name="t",
                slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
            )
        )
        reg.create_compilation_config(CompilationConfig(name="p", template_name="t"))
        return reg

    import sys
    monkeypatch.setattr(
        sys.modules[__name__], "_fail_factory", factory_with_failure, raising=False,
    )
    rc = cli_main([
        "test",
        f"{__name__}:_fail_factory",
        "--config", "p",
        "--results", str(tmp_path / "r.jsonl"),
    ])
    assert rc == 1
