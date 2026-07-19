"""Interactive-tier evaluator — the realtime runner as an autoloop target.

Everything runs offline: a scripted ChatClient stands in for the live
provider, exactly the mock-gate tier the evaluator is designed to allow.
"""

from __future__ import annotations

from open_agent_compiler.improvement import (
    Criterion,
    IdentityMutator,
    IterativeLoop,
    OptimisationCriterion,
    OptimizationTarget,
    Probe,
    PromptPrefixMutator,
    build_interactive_evaluator,
    run_per_target_loops,
    score_interactive_spec,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.interactive.runner import ChatResponse, ChatToolCall
from open_agent_compiler.interactive.spec import InteractiveAgentSpec, ToolSpec
from open_agent_compiler.model.core.model_preset import ModelPreset, SamplingDefaults
from open_agent_compiler.model.core.test_model import (
    SubstringEvaluator,
    ToolCalledEvaluator,
)


def _preset() -> ModelPreset:
    return ModelPreset(
        name="local", provider="local-vllm", model_id="test-model",
        sampling=SamplingDefaults(temperature=0.0),
    )


def _spec(system_prompt: str, tools: tuple[ToolSpec, ...] = ()) -> InteractiveAgentSpec:
    return InteractiveAgentSpec(
        agent_id="greeter", model=_preset(),
        system_prompt=system_prompt, tools=tools,
    )


class _EchoPromptClient:
    """Scripted model: replies with the system prompt so evaluators can
    observe exactly which candidate rendering reached the model."""

    def complete(self, *, messages, tools, model, **params):
        return ChatResponse(content=f"SYSTEM WAS: {messages[0]['content']}")


class _ToolThenAnswerClient:
    """Scripted model: first turn calls the tool, second turn answers."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, *, messages, tools, model, **params):
        self.turn += 1
        if self.turn == 1:
            return ChatResponse(tool_calls=[
                ChatToolCall(id="1", name="lookup", args={"q": "x"}),
            ])
        return ChatResponse(content="the answer is 42")


def _criterion() -> OptimisationCriterion:
    return OptimisationCriterion(
        name="passes",
        criteria=(Criterion(kind="pass_rate", target=1.0, hard=True),),
    )


# ---- score_interactive_spec (benchmark half) ---------------------------


def test_score_interactive_spec_scores_output_text() -> None:
    metrics = score_interactive_spec(
        _spec("You are POLITE."),
        [Probe(probe_id="p", payload="hi",
               evaluators=(SubstringEvaluator(needle="POLITE"),))],
        client=_EchoPromptClient(),
    )
    assert metrics["pass_rate"] == 1.0
    assert metrics["score_floor"] == 1.0
    assert "score_floor:by_name:p" in metrics


def test_score_interactive_spec_sees_tool_calls() -> None:
    tools = (ToolSpec(name="lookup", description="look things up"),)
    metrics = score_interactive_spec(
        _spec("You may use tools.", tools),
        [Probe(probe_id="uses-tool", payload="find x",
               evaluators=(ToolCalledEvaluator(tool_name="lookup"),
                           SubstringEvaluator(needle="42")))],
        client=_ToolThenAnswerClient(),
        tool_runner=lambda name, args: "looked-up-value",
    )
    assert metrics["pass_rate"] == 1.0


def test_interactive_run_error_scores_probe_zero() -> None:
    """A model that keeps demanding tools with no runner → error → 0."""

    class _AlwaysTools:
        def complete(self, *, messages, tools, model, **params):
            return ChatResponse(tool_calls=[ChatToolCall(name="lookup")])

    tools = (ToolSpec(name="lookup", description="d"),)
    metrics = score_interactive_spec(
        _spec("s", tools),
        [Probe(probe_id="p", payload="hi",
               evaluators=(SubstringEvaluator(needle="anything"),))],
        client=_AlwaysTools(),
    )
    assert metrics["pass_rate"] == 0.0
    assert metrics["score_floor"] == 0.0


# ---- build_interactive_evaluator inside a loop -------------------------


def _baseline() -> ComponentVersion:
    return ComponentVersion.of(
        component_id="greeter", kind="agent",
        definition={"system_prompt": "be helpful"},
    )


def _spec_factory(defn: dict) -> InteractiveAgentSpec:
    return _spec(defn["system_prompt"])


def test_loop_with_interactive_evaluator_prefers_mutated_prompt() -> None:
    """The prefix mutator wins because only its rendering contains the needle."""
    evaluator = build_interactive_evaluator(
        [Probe(probe_id="p", payload="hi",
               evaluators=(SubstringEvaluator(needle="CRITICAL"),))],
        _spec_factory,
        client=_EchoPromptClient(),
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
    assert best is not None
    assert best.definition["system_prompt"].startswith("CRITICAL: ")
    assert best.metrics["pass_rate"] == 1.0


def test_interactive_as_target_in_per_target_loops(tmp_path) -> None:
    """'interactive' is just another cell of the adaptation matrix."""
    def evaluator_factory(target: OptimizationTarget):
        if target.harness == "interactive":
            return build_interactive_evaluator(
                [Probe(probe_id="p", payload="hi",
                       evaluators=(SubstringEvaluator(needle="SYSTEM"),))],
                _spec_factory,
                client=_EchoPromptClient(),
            )
        return lambda v: {"pass_rate": 1.0}

    out = run_per_target_loops(
        baseline=_baseline(),
        mutators=[IdentityMutator()],
        criterion=_criterion(),
        targets=[
            OptimizationTarget(harness="opencode", model_class="fast"),
            OptimizationTarget(harness="interactive"),
        ],
        evaluator_factory=evaluator_factory,
        max_rounds=1,
        output=tmp_path / "improved",
    )
    assert set(out) == {"opencode+fast", "interactive"}
    assert (tmp_path / "improved" / "greeter" / "interactive" / "LATEST.json").exists()


def test_probe_payload_dict_threads_history() -> None:
    """A dict payload carries history so probes can test multi-turn state."""
    seen: dict = {}

    class _CaptureClient:
        def complete(self, *, messages, tools, model, **params):
            seen["messages"] = messages
            return ChatResponse(content="ok")

    score_interactive_spec(
        _spec("s"),
        [Probe(probe_id="p",
               payload={"user_input": "and now?",
                        "history": [{"role": "user", "content": "earlier"},
                                    {"role": "assistant", "content": "noted"}]},
               evaluators=(SubstringEvaluator(needle="ok"),))],
        client=_CaptureClient(),
    )
    roles = [m["role"] for m in seen["messages"][:4]]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen["messages"][3]["content"] == "and now?"
