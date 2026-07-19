"""Per-target promotion slots: promote --target + target > class > default resolution."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.snapshot import (
    apply_promoted_to_agent,
    find_promoted_snapshot,
    load_promoted_definition,
    promote,
    write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader


def _version(prompt: str) -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind="agent",
        definition={"name": "orch", "system_prompt": prompt},
    )


def _snap_path(tmp_path: Path, prompt: str) -> Path:
    return write_snapshot(_version(prompt), tmp_path / "improved")


def _agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id="orch", name="orch", description="d"),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="baseline prompt",
    )


def test_promote_with_target_writes_target_slot(tmp_path: Path) -> None:
    dest = promote(
        _snap_path(tmp_path, "pi-tuned"), tmp_path, target="pi+fast",
    )
    assert dest.name == "orch__pi+fast.json"
    assert dest.parent == tmp_path / ".oac" / "promoted"


def test_target_takes_precedence_over_model_class_in_promote(tmp_path: Path) -> None:
    dest = promote(
        _snap_path(tmp_path, "x"), tmp_path,
        model_class="fast", target="pi+fast",
    )
    assert dest.name == "orch__pi+fast.json"


def test_resolution_order_target_then_class_then_default(tmp_path: Path) -> None:
    promote(_snap_path(tmp_path, "default-tuned"), tmp_path)
    promote(_snap_path(tmp_path, "class-tuned"), tmp_path, model_class="fast")
    promote(_snap_path(tmp_path, "target-tuned"), tmp_path, target="pi+fast")

    hit = find_promoted_snapshot(
        "orch", tmp_path, model_class="fast", target="pi+fast",
    )
    assert hit is not None
    assert hit.version.definition["system_prompt"] == "target-tuned"

    # No target slot for this key → falls back to class slot.
    hit = find_promoted_snapshot(
        "orch", tmp_path, model_class="fast", target="opencode+fast",
    )
    assert hit is not None
    assert hit.version.definition["system_prompt"] == "class-tuned"

    # Neither target nor class slot → default.
    hit = find_promoted_snapshot(
        "orch", tmp_path, model_class="vision", target="codex+vision",
    )
    assert hit is not None
    assert hit.version.definition["system_prompt"] == "default-tuned"


def test_load_promoted_definition_accepts_target(tmp_path: Path) -> None:
    promote(_snap_path(tmp_path, "interactive-tuned"), tmp_path, target="interactive")
    defn = load_promoted_definition("orch", tmp_path, target="interactive")
    assert defn is not None
    assert defn["system_prompt"] == "interactive-tuned"


def test_apply_promoted_to_agent_with_target(tmp_path: Path) -> None:
    promote(_snap_path(tmp_path, "pi-fast-winner"), tmp_path, target="pi+fast")
    merged = apply_promoted_to_agent(_agent(), "orch", tmp_path, target="pi+fast")
    assert merged.system_prompt == "pi-fast-winner"


def test_apply_promoted_to_agent_target_falls_back_to_default(tmp_path: Path) -> None:
    promote(_snap_path(tmp_path, "shared-winner"), tmp_path)
    merged = apply_promoted_to_agent(_agent(), "orch", tmp_path, target="pi+fast")
    assert merged.system_prompt == "shared-winner"


def test_no_promotion_is_a_noop_with_target(tmp_path: Path) -> None:
    merged = apply_promoted_to_agent(_agent(), "orch", tmp_path, target="pi+fast")
    assert merged.system_prompt == "baseline prompt"
