"""Phase E keystone — PersonalizationRun end-to-end, fully MOCKED.

Asserts the per-client deep-tool-use autoloop wires together correctly with NO
live opencode/qwen/z.ai/network: compile -> seed probes -> evaluate full session
-> judge -> promote per-client, over the JOINT mutation space.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_agent_compiler.improvement.mutators import (
    LLMPromptRewriter,
    ToolDescriptionAppendMutator,
    ToolFormatMutator,
    ToolRuleAddMutator,
    ToolSelectionMutator,
    ToolSequenceMutator,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.capability_bundle import ClientCapabilityBundle, ClientMCPServer
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.personalization.run import PersonalizationRun, build_joint_mutators
from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask

CLIENT_GOAL = "Triage support emails and draft on-brand replies"
GOAL_MARKER = "Triage support emails"


# ---- fakes (the only IO seams) -----------------------------------------


class FakeSessionRunner:
    """Stand-in OpencodeRunner: the session output reflects the candidate's prompt.

    In a real run, `agent_name_for` installs the candidate's compiled .md (with
    its tuned system_prompt) as a flat agent and the runner runs THAT agent, so
    the session realises whatever the candidate's prompt instructs. Here the
    `installed` map (populated by the test's `agent_name_for`) supplies the
    candidate's system_prompt for the agent name, and the 'session output' is
    that prompt — so an improved candidate (prompt mentions the client goal)
    scores higher under the judge.
    """

    def __init__(self, installed: dict[str, str]) -> None:
        self.calls: list[dict] = []
        self.installed = installed

    def run(self, *, agent_name: str, prompt: str, **kw):
        self.calls.append({"agent": agent_name, "prompt": prompt})
        system = self.installed.get(agent_name, "")
        return _FakeResult(f"{system}\n[answering: {prompt}]")


class _FakeResult:
    def __init__(self, text: str) -> None:
        self._text = text
        self.error = None

    def final_text(self) -> str:
        return self._text

    def subagent_dispatch_chain(self):
        return []


class FakeJudge:
    """Scores high when the session realised the client's goal, low otherwise."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def judge(self, criteria, target, *, model=None):
        self.calls.append((criteria, str(target)))
        score = 0.95 if GOAL_MARKER in str(target) else 0.2
        return {"pass": score >= 0.7, "score": score, "reasoning": "stub"}


class FakeTeacher:
    """LLMMutatorClient stub: rewrites a prompt to mention the client goal."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def rewrite(self, target, guidance, *, context=None, model=None):
        self.calls.append({"target": target, "guidance": guidance})
        # The teacher realises the workflow by stating the client goal explicitly.
        return f"{target}\n\n{CLIENT_GOAL} — handle each step with the right tool."


# ---- fixtures ----------------------------------------------------------


def _spec() -> ClientSpec:
    return ClientSpec(
        goal=CLIENT_GOAL,
        preferences=("Friendly, concise tone",),
        constraints=("Never promise a refund",),
        example_tasks=(
            ExampleTask(prompt="Customer says order #12 never arrived. Reply."),
            ExampleTask(prompt="Customer asks to reset password."),
        ),
        success_criteria=("Reply is on-topic, friendly, and within constraints",),
    )


def _bundle() -> ClientCapabilityBundle:
    return ClientCapabilityBundle(
        client_id="acme",
        builtin_tools=("search", "draft"),
        mcp_servers=(
            ClientMCPServer(
                name="acme_drive", transport="remote",
                url="https://mcp.acme/drive", tools=("drive_search",),
            ),
        ),
    )


def _factory():
    reg = AgentRegistry()
    a = AgentDefinition(
        header=AgentHeader(agent_id="support", name="support-bot", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        # weak baseline: does NOT mention the client goal yet
        system_prompt="You answer messages.",
    )
    aid = reg.register_agent(
        "primary", a, ModelParameters(model_name="local/qwen", temperature=0.7)
    )
    reg.register_template(
        TemplateTree(name="tpl", slots=[TemplateSlot(name="primary", default_agent_id=aid)])
    )
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg


def _preset():
    return ModelPreset(
        name="o", provider="vllm", model_id="x",
        sampling=SamplingDefaults(temperature=0.0),
    )


# ---- joint mutation space ----------------------------------------------


def test_joint_mutators_cover_prompt_and_tool_axes():
    mutators = build_joint_mutators(
        _spec(),
        client_tool_names=("drive_search",),
        disablable_tools=("draft",),
    )
    kinds = {type(m) for m in mutators}
    assert LLMPromptRewriter in kinds
    assert ToolDescriptionAppendMutator in kinds
    assert ToolRuleAddMutator in kinds
    assert ToolFormatMutator in kinds
    assert ToolSelectionMutator in kinds
    assert ToolSequenceMutator in kinds
    # the rewriter's guidance is derived from the client's goal/constraints
    rw = next(m for m in mutators if isinstance(m, LLMPromptRewriter))
    assert CLIENT_GOAL in rw.guidance
    assert "Never promise a refund" in rw.guidance


# ---- full end-to-end ----------------------------------------------------


def test_personalization_run_end_to_end(tmp_path: Path):
    from open_agent_compiler.personalization.compile import compile_personalized

    spec, bundle = _spec(), _bundle()
    project = tmp_path / "acme_project"

    # 1) personalized compile produces the per-client opencode project root
    compiled = compile_personalized(
        "acme", spec, bundle, project,
        factory=_factory, config="prod", preset=_preset(),
    )
    cfg = json.loads(compiled.opencode_json.read_text())
    # personalized opencode.json carries the client MCP + merged allow-list
    assert "acme_drive" in cfg["mcp"]
    assert "drive_search" in cfg["tools"]
    assert "search" in cfg["tools"] and "draft" in cfg["tools"]

    # baseline = the overlaid agent definition (its prompt already has client ctx)
    reg = _factory()
    baseline_defn = reg.resolve_config("prod")["primary"].agent_definition.model_dump()
    # strip the goal so promotion depends on the loop improving it (not the base)
    baseline_defn["system_prompt"] = "You answer messages."

    installed: dict[str, str] = {}
    runner, judge, teacher = FakeSessionRunner(installed), FakeJudge(), FakeTeacher()

    # candidate -> flat agent name; install its system_prompt so the session
    # realises the candidate (mirrors flat_candidate_from_project_root).
    def agent_name_for(version: ComponentVersion) -> str:
        name = f"cand_{version.content_hash[:8]}"
        installed[name] = version.definition.get("system_prompt", "")
        return name

    run = PersonalizationRun(
        client_id="acme",
        client_spec=spec,
        capability_bundle=bundle,
        target=0.7,
        max_rounds=2,
    )

    # 2) the run seeds probes from the spec
    result = run.run(
        baseline_definition=baseline_defn,
        runner=runner,
        judge=judge,
        teacher=teacher,
        agent_name_for=agent_name_for,
        project_root=project,
        snapshots_dir=project / ".oac" / "snapshots",
    )

    # probes seeded from the spec's two example tasks
    assert result.probe_keys == ["example_task:0", "example_task:1"]
    probes_file = project / ".oac" / "acme" / "probes.json"
    assert probes_file.exists()
    seeded = json.loads(probes_file.read_text())
    assert any("order #12" in v for v in seeded.values())

    # 3) a full session was run for each probe (student via OpencodeRunner seam)
    assert runner.calls, "no opencode session was run"
    # 4) the judge graded sessions; the teacher rewrote the prompt
    assert judge.calls, "judge never invoked"
    assert teacher.calls, "teacher never invoked"

    # 5) a winner cleared the client bar and promoted into the CLIENT bucket
    assert result.promoted is True
    assert result.winner_score >= 0.7
    promoted_dir = project / ".oac" / "promoted" / "acme"
    assert promoted_dir.exists()
    promoted_files = list(promoted_dir.glob("*.json"))
    assert promoted_files, "nothing promoted into .oac/promoted/acme/"
    # the promoted snapshot is the goal-realising candidate
    snap = json.loads(promoted_files[0].read_text())
    assert GOAL_MARKER in snap["version"]["definition"]["system_prompt"]


def test_run_requires_usable_spec(tmp_path: Path):
    unusable = ClientSpec(goal="g")  # no example_tasks / success_criteria
    run = PersonalizationRun(
        client_id="acme", client_spec=unusable, capability_bundle=_bundle(),
    )
    with pytest.raises(ValueError, match="not usable"):
        run.run(
            baseline_definition={"header": {"agent_id": "x"}, "system_prompt": "p"},
            runner=FakeSessionRunner({}), judge=FakeJudge(), teacher=FakeTeacher(),
            agent_name_for=lambda v: "cand_x", project_root=tmp_path,
        )


def test_errored_session_scores_zero(tmp_path: Path):
    """A discovery/provider failure must score 0, never silently pass."""
    from open_agent_compiler.personalization.run import build_session_judge_evaluator
    from open_agent_compiler.personalization.probes import seed_probes_from_spec

    spec = _spec()
    probes = seed_probes_from_spec(spec, tmp_path / "probes.json")

    class ErroringRunner:
        def run(self, *, agent_name, prompt, **kw):
            class R:
                error = "opencode error: Agent not found"
                def final_text(self):
                    return ""
                def subagent_dispatch_chain(self):
                    return []
            return R()

    failures: list = []
    ev = build_session_judge_evaluator(
        spec=spec, probes=probes,
        probe_keys=["example_task:0", "example_task:1"],
        runner=ErroringRunner(), judge=FakeJudge(),
        agent_name_for=lambda v: "cand_x", failures_sink=failures,
    )
    v = ComponentVersion.of("support", "agent", {"system_prompt": "p"})
    metrics = ev(v)
    assert metrics["score_floor:by_evaluator:llm_judge"] == 0.0
    assert metrics["pass_rate"] == 0.0
    assert failures and "Agent not found" in failures[0]["error"]


# ---- tool-discipline / flailing signal forwarding ----------------------


class _BlockedResult:
    """Session result whose model flailed on denied tools (allow-list)."""

    error = None

    def __init__(self, text: str, blocked: list[tuple[str, str]]) -> None:
        self._text = text
        self._blocked = blocked

    def final_text(self) -> str:
        return self._text

    def subagent_dispatch_chain(self):
        return []

    def blocked_tool_details(self) -> list[tuple[str, str]]:
        return self._blocked


class _NoteReadingJudge:
    """Judge that DROPS the score when it SEES the forwarded TOOL DISCIPLINE note.

    This proves the rubric's flailing clause can actually fire: the judge only
    knows about blocked tools because the note was appended to what it grades.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    def judge(self, criteria, target, *, model=None):
        self.seen.append(str(target))
        score = 0.2 if "TOOL DISCIPLINE" in str(target) else 0.95
        return {"pass": score >= 0.7, "score": score, "reasoning": "stub"}


def test_blocked_tool_attempts_forwarded_to_judge_and_failures(tmp_path: Path):
    """Denied tool calls → the judge SEES a blocked-attempt note AND failures
    capture them (even though the session itself did not error)."""
    from open_agent_compiler.personalization.run import build_session_judge_evaluator
    from open_agent_compiler.personalization.probes import seed_probes_from_spec

    spec = _spec()
    probes = seed_probes_from_spec(spec, tmp_path / "probes.json")

    class FlailingRunner:
        def run(self, *, agent_name, prompt, **kw):
            return _BlockedResult(
                "a real-ish answer",
                [("ls", "a rule prevents you from using ls"),
                 ("read", "a rule prevents you from using read")],
            )

    judge = _NoteReadingJudge()
    failures: list = []
    ev = build_session_judge_evaluator(
        spec=spec, probes=probes, probe_keys=["example_task:0"],
        runner=FlailingRunner(), judge=judge,
        agent_name_for=lambda v: "cand_x", failures_sink=failures,
    )
    v = ComponentVersion.of("support", "agent", {"system_prompt": "p"})
    metrics = ev(v)

    # the judge was shown the blocked-attempt note (not prose alone)
    assert any("TOOL DISCIPLINE" in s and "ls" in s and "read" in s
               for s in judge.seen)
    assert any("DENIED/blocked tool" in s for s in judge.seen)
    # failures captured the blocked attempts for the teacher's next rewrite
    assert failures and failures[0]["blocked_attempts"] == 2
    assert set(failures[0]["blocked_tools"]) == {"ls", "read"}
    # and the forwarded signal pulled the score down
    assert metrics["score_floor:by_evaluator:llm_judge"] < 0.7


def test_flailing_candidate_scores_lower_than_clean(tmp_path: Path):
    """The keystone: a flailing candidate scores strictly LOWER than an
    otherwise-identical clean one, because the blocked-attempt note is forwarded
    to the (note-reading) judge."""
    from open_agent_compiler.personalization.run import build_session_judge_evaluator
    from open_agent_compiler.personalization.probes import seed_probes_from_spec

    spec = _spec()
    probes = seed_probes_from_spec(spec, tmp_path / "probes.json")

    class CleanRunner:
        def run(self, *, agent_name, prompt, **kw):
            return _BlockedResult("a real-ish answer", [])

    class FlailingRunner:
        def run(self, *, agent_name, prompt, **kw):
            return _BlockedResult(
                "a real-ish answer",
                [("find", "a rule prevents you from using find")],
            )

    def _score(runner) -> float:
        ev = build_session_judge_evaluator(
            spec=spec, probes=probes, probe_keys=["example_task:0"],
            runner=runner, judge=_NoteReadingJudge(),
            agent_name_for=lambda v: "cand_x", failures_sink=[],
        )
        v = ComponentVersion.of("support", "agent", {"system_prompt": "p"})
        return ev(v)["score_floor:by_evaluator:llm_judge"]

    clean = _score(CleanRunner())
    flailing = _score(FlailingRunner())
    assert flailing < clean, (flailing, clean)
