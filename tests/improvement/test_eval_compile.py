"""eval_compile — primary-mode .md emission + parent-mimic prompt."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.eval_compile import (
    build_parent_mimic_prompt,
    write_test_variant_md,
)
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader


def _agent(prompt: str = "judge the input") -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="judge", name="judge",
            description="One-shot judge subagent.",
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=prompt,
    )


def test_write_test_variant_md_emits_primary_mode(tmp_path: Path) -> None:
    name, path = write_test_variant_md(
        _agent("you score things"),
        build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
    )
    assert name.startswith("eval_variant_")
    src = path.read_text()
    assert "mode: primary" in src
    assert "model: zai-coding-plan/glm-4.5-air" in src
    assert "you score things" in src


def test_write_test_variant_uses_name_prefix(tmp_path: Path) -> None:
    name, _ = write_test_variant_md(
        _agent(), build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
        name_prefix="scorer_eval",
    )
    assert name.startswith("scorer_eval_")


def test_write_test_variant_lands_under_opencode_agents(tmp_path: Path) -> None:
    _, path = write_test_variant_md(
        _agent(), build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
    )
    rel = path.relative_to(tmp_path / "build")
    assert rel.parts[0] == ".opencode"
    assert rel.parts[1] == "agents"


def test_write_test_variant_supports_extra_permissions(
    tmp_path: Path,
) -> None:
    _, path = write_test_variant_md(
        _agent(), build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
        extra_permissions={"task": "allow"},
    )
    src = path.read_text()
    # Scalar strings get JSON-quoted by the lightweight emitter.
    assert 'task: "allow"' in src or "task: allow" in src


def test_two_variants_get_unique_names(tmp_path: Path) -> None:
    n1, _ = write_test_variant_md(
        _agent(), build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
    )
    n2, _ = write_test_variant_md(
        _agent(), build_dir=tmp_path / "build",
        model="zai-coding-plan/glm-4.5-air",
    )
    assert n1 != n2


def test_parent_mimic_prompt_includes_role_framing() -> None:
    out = build_parent_mimic_prompt(
        target_agent_name="transcript-scorer",
        target_description="Score adherence 0-1.",
        eval_case={
            "id": "case_0",
            "excerpt": "some transcript content",
            "query": "what we want",
            "expected_score": 0.7,  # excluded from prompt body
        },
        parent_description="channel-finder",
    )
    assert "channel-finder" in out
    assert "transcript-scorer" in out
    assert "what we want" in out
    assert "some transcript content" in out
    # expected_score is metadata for the eval, not for the agent.
    assert "0.7" not in out


def test_parent_mimic_prompt_works_without_parent_description() -> None:
    out = build_parent_mimic_prompt(
        target_agent_name="x", target_description="d",
        eval_case={"q": "hello"},
    )
    assert "parent orchestrator" in out
