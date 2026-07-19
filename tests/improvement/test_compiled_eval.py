"""build_compiled_evaluator — compile → run → judge with an injected runner."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement import (
    Criterion,
    IdentityMutator,
    IterativeLoop,
    OptimisationCriterion,
    OptimizationTarget,
    Probe,
    PromptPrefixMutator,
    build_compiled_evaluator,
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
from open_agent_compiler.model.core.test_model import SubstringEvaluator


def _registry_factory(defn: dict) -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="summarizer", name="summarizer",
                           description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=str(defn.get("system_prompt", "")),
    )
    aid = reg.register_agent("summarizer", agent, ModelParameters(model_name="m"))
    reg.register_template(TemplateTree(
        name="t", slots=[TemplateSlot(name="summarizer", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="t"))
    return reg


class _CompiledFileRunner:
    """Stub harness runner: 'runs' the agent by reading its compiled .pi
    file — proving the evaluator really compiled THIS candidate."""

    harness_name = "pi"

    def __init__(self, build_dir: Path) -> None:
        self.build_dir = build_dir
        self.calls: list[str] = []

    def run(self, *, agent_name: str, prompt: str, timeout_s=None):
        self.calls.append(prompt)
        compiled = (self.build_dir / ".pi" / "agents" / f"{agent_name}.md").read_text()

        class _R:
            error = None
            succeeded = True

            def final_text(self_inner) -> str:
                return compiled

        return _R()


class _FailingRunner:
    harness_name = "pi"

    def run(self, *, agent_name, prompt, timeout_s=None):
        class _R:
            error = "pi exit 3: boom"
            succeeded = False

            def final_text(self_inner) -> str:
                return ""

        return _R()


def _baseline() -> ComponentVersion:
    return ComponentVersion.of(
        component_id="summarizer", kind="agent",
        definition={"system_prompt": "Summarize things."},
    )


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="passes", criteria=(Criterion(kind="pass_rate", target=1.0, hard=False),),
    )


def test_compiled_evaluator_compiles_candidate_and_scores(tmp_path: Path) -> None:
    build_dir = tmp_path / "eval_build"
    runner = _CompiledFileRunner(build_dir)
    evaluator = build_compiled_evaluator(
        [Probe(probe_id="carries-prefix", payload="summarize X",
               evaluators=(SubstringEvaluator(needle="CRITICAL"),))],
        registry_factory=_registry_factory,
        target=OptimizationTarget(harness="pi", model_class="fast"),
        build_dir=build_dir,
        config="prod",
        agent_name="summarizer",
        runner=runner,
    )
    loop = IterativeLoop(
        baseline=_baseline(),
        mutators=[IdentityMutator(), PromptPrefixMutator("CRITICAL: ")],
        criterion=_criterion(),
        evaluator=evaluator,
        max_rounds=1,
        frontier_size=2,
    )
    result = loop.run()
    best = result.best(metric="pass_rate")
    assert best.definition["system_prompt"].startswith("CRITICAL: ")
    assert best.metrics["pass_rate"] == 1.0
    # The probe prompt actually reached the runner.
    assert "summarize X" in runner.calls
    # And each candidate really was compiled into the build dir.
    assert (build_dir / ".pi" / "agents" / "summarizer.md").exists()


def test_harness_failure_scores_probe_zero(tmp_path: Path) -> None:
    evaluator = build_compiled_evaluator(
        [Probe(probe_id="p", payload="x",
               evaluators=(SubstringEvaluator(needle="anything"),))],
        registry_factory=_registry_factory,
        target=OptimizationTarget(harness="pi"),
        build_dir=tmp_path / "b",
        config="prod",
        agent_name="summarizer",
        runner=_FailingRunner(),
    )
    metrics = evaluator(_baseline())
    assert metrics["pass_rate"] == 0.0
    assert metrics["score_floor"] == 0.0


def test_dict_payload_uses_prompt_key(tmp_path: Path) -> None:
    build_dir = tmp_path / "b"
    runner = _CompiledFileRunner(build_dir)
    evaluator = build_compiled_evaluator(
        [Probe(probe_id="p", payload={"prompt": "from-dict", "note": "x"})],
        registry_factory=_registry_factory,
        target=OptimizationTarget(harness="pi"),
        build_dir=build_dir,
        config="prod",
        agent_name="summarizer",
        runner=runner,
    )
    evaluator(_baseline())
    assert runner.calls == ["from-dict"]
