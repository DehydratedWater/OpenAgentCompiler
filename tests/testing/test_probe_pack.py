"""ProbePack: load + pack→AgentTest conversion."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler import PackProbe, ProbePack, load_pack, pack_to_tests


def _pack() -> ProbePack:
    return ProbePack(
        agent_id="persona/orchestrator",
        generated_at="2026-06-11T00:00:00Z",
        source="v3-corpus",
        teacher="glm-5.1",
        probes=[
            PackProbe(name="trivial_greeting", prompt="hey, how's it going?",
                      criteria="Routes trivial greeting to quick_ack."),
            PackProbe(name="multi_intent", prompt="mark groceries done and remind me",
                      criteria="Detects two intents.", pass_threshold=0.8),
        ],
    )


def test_pack_to_tests_shapes_names_prompts_and_thresholds() -> None:
    tests = pack_to_tests(_pack(), prompt_suffix="\n\nANTI-META")
    assert [t.name for t in tests] == [
        "persona/orchestrator::pack:trivial_greeting",
        "persona/orchestrator::pack:multi_intent",
    ]
    assert tests[0].prompt.endswith("ANTI-META")
    judge = tests[1].evaluators[0]
    assert judge.kind == "llm_judge"
    assert judge.pass_threshold == 0.8
    assert judge.criteria == "Detects two intents."


def test_custom_name_prefix() -> None:
    tests = pack_to_tests(_pack(), name_prefix="probe:")
    assert tests[0].name == "probe:trivial_greeting"


def test_load_pack_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "pack.json"
    p.write_text(_pack().model_dump_json())
    loaded = load_pack(p)
    assert loaded is not None
    assert loaded.agent_id == "persona/orchestrator"
    assert len(loaded.probes) == 2


def test_load_pack_missing_and_corrupt_return_none(tmp_path: Path) -> None:
    assert load_pack(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"agent_id": "x", "probes": []}))  # min_length=1
    assert load_pack(bad) is None
