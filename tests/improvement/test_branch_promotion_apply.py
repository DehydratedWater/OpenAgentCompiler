"""Branch-level (orchestrator) promotions must actually APPLY at compile.

The per-branch autoloop promotes an improved orchestrator under component id
``branch:<entry>`` (kind="agent"; definition = the improved orchestrator
``AgentDefinition`` dump). But the apply/resolve path historically resolved
promotions only by an agent's OWN id (``funfact`` / ``goals/priority_orchestrator``),
so a ``branch:<id>`` promotion was computed yet inert.

These tests pin the additive resolution:
  - an agent with ONLY a ``branch:<id>`` promotion picks it up;
  - with BOTH, the HIGHER-score one wins (both directions; tie → branch);
  - with ONLY ``<id>``, behaviour is unchanged from before (regression);
  - it composes with a ``client_id`` bucket.

Pure / mocked — no live opencode, qwen, or z.ai.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.improvement.snapshot import (
    apply_promoted_to_agent,
    apply_promoted_to_tree,
    find_promoted_snapshot_with_branch,
    promote,
    write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader


def _agent(agent_id: str = "funfact", prompt: str = "weak") -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(agent_id=agent_id, name=agent_id, description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt=prompt,
        todo_mode="strict",
    )


def _promote(
    project: Path,
    component_id: str,
    prompt: str,
    *,
    score_floor: float | None = None,
    pass_rate: float | None = None,
    client_id: str | None = None,
) -> None:
    """Promote a ComponentVersion for `component_id` carrying a recorded score."""
    metrics: dict[str, float] = {}
    if score_floor is not None:
        metrics["score_floor"] = score_floor
    if pass_rate is not None:
        metrics["pass_rate"] = pass_rate
    v = ComponentVersion.of(
        component_id=component_id, kind="agent",
        definition={"name": component_id, "system_prompt": prompt},
        metrics=metrics,
    )
    snap_path = write_snapshot(v, project / "improved")
    promote(snap_path, project, client_id=client_id)


# ---- only a branch:<id> promotion -------------------------------------


def test_branch_only_promotion_is_applied(tmp_path: Path) -> None:
    """An agent with ONLY a ``branch:<id>`` promotion gets it applied."""
    _promote(tmp_path, "branch:funfact", "BRANCH-IMPROVED", score_floor=0.85)
    out = apply_promoted_to_agent(_agent("funfact", "weak"), "funfact", tmp_path)
    assert out.system_prompt == "BRANCH-IMPROVED"


def test_branch_only_promotion_with_slash_id(tmp_path: Path) -> None:
    """Branch id resolution honours the ``/`` → ``__`` filename encoding.

    ``branch:goals/priority_orchestrator`` must load from the on-disk file
    ``branch:goals__priority_orchestrator.json`` — matching how the real v4
    promotions are named.
    """
    _promote(
        tmp_path, "branch:goals/priority_orchestrator",
        "ORCH-IMPROVED", score_floor=0.85,
    )
    out = apply_promoted_to_agent(
        _agent("orch", "weak"), "goals/priority_orchestrator", tmp_path,
    )
    assert out.system_prompt == "ORCH-IMPROVED"


# ---- both <id> and branch:<id> → higher score wins --------------------


def test_branch_wins_when_higher(tmp_path: Path) -> None:
    _promote(tmp_path, "funfact", "AGENT", score_floor=0.75)
    _promote(tmp_path, "branch:funfact", "BRANCH", score_floor=0.85)
    out = apply_promoted_to_agent(_agent("funfact"), "funfact", tmp_path)
    assert out.system_prompt == "BRANCH"


def test_agent_wins_when_higher(tmp_path: Path) -> None:
    _promote(tmp_path, "funfact", "AGENT", score_floor=0.90)
    _promote(tmp_path, "branch:funfact", "BRANCH", score_floor=0.85)
    out = apply_promoted_to_agent(_agent("funfact"), "funfact", tmp_path)
    assert out.system_prompt == "AGENT"


def test_tie_prefers_branch(tmp_path: Path) -> None:
    """On an exact score tie, the branch (full-session) promotion wins."""
    _promote(tmp_path, "funfact", "AGENT", score_floor=0.85)
    _promote(tmp_path, "branch:funfact", "BRANCH", score_floor=0.85)
    out = apply_promoted_to_agent(_agent("funfact"), "funfact", tmp_path)
    assert out.system_prompt == "BRANCH"


def test_pass_rate_fallback_when_no_score_floor(tmp_path: Path) -> None:
    """When ``score_floor`` is absent, ``pass_rate`` is the comparison key."""
    _promote(tmp_path, "funfact", "AGENT", pass_rate=0.6)
    _promote(tmp_path, "branch:funfact", "BRANCH", pass_rate=0.9)
    out = apply_promoted_to_agent(_agent("funfact"), "funfact", tmp_path)
    assert out.system_prompt == "BRANCH"


# ---- regression: only <id> unchanged from today -----------------------


def test_agent_only_promotion_unchanged(tmp_path: Path) -> None:
    """An agent with only an ``<id>`` promotion behaves exactly as before."""
    _promote(tmp_path, "funfact", "AGENT", score_floor=0.75)
    out = apply_promoted_to_agent(_agent("funfact"), "funfact", tmp_path)
    assert out.system_prompt == "AGENT"


def test_no_promotion_is_noop(tmp_path: Path) -> None:
    base = _agent("funfact", "weak")
    out = apply_promoted_to_agent(base, "funfact", tmp_path)
    assert out is base


# ---- composes with a client_id bucket ---------------------------------


def test_branch_in_client_bucket_applies(tmp_path: Path) -> None:
    """A ``branch:<id>`` promotion living in a client bucket is resolved."""
    _promote(
        tmp_path, "branch:funfact", "CLIENT-BRANCH",
        score_floor=0.85, client_id="acme",
    )
    out = apply_promoted_to_agent(
        _agent("funfact"), "funfact", tmp_path, client_id="acme",
    )
    assert out.system_prompt == "CLIENT-BRANCH"


def test_client_branch_beats_base_agent(tmp_path: Path) -> None:
    """Within the client compile, the client branch promotion is compared
    against the client/base resolution of the agent id and the higher wins.

    Base bucket has a low-score agent promotion; the client bucket has a
    higher-score branch promotion → branch wins for that client.
    """
    _promote(tmp_path, "funfact", "BASE-AGENT", score_floor=0.70)
    _promote(
        tmp_path, "branch:funfact", "CLIENT-BRANCH",
        score_floor=0.90, client_id="acme",
    )
    out = apply_promoted_to_agent(
        _agent("funfact"), "funfact", tmp_path, client_id="acme",
    )
    assert out.system_prompt == "CLIENT-BRANCH"


def test_client_branch_falls_back_to_base_branch(tmp_path: Path) -> None:
    """A client with no own promotions inherits the base branch promotion."""
    _promote(tmp_path, "branch:funfact", "BASE-BRANCH", score_floor=0.85)
    out = apply_promoted_to_agent(
        _agent("funfact"), "funfact", tmp_path, client_id="acme",
    )
    assert out.system_prompt == "BASE-BRANCH"


# ---- applies through the whole tree path (register surface) -----------


def test_apply_promoted_to_tree_uses_branch(tmp_path: Path) -> None:
    """``apply_promoted_to_tree`` (the register_with_improvements surface)
    picks up a branch promotion for the tree's root agent."""
    _promote(tmp_path, "branch:funfact", "TREE-BRANCH", score_floor=0.85)
    out = apply_promoted_to_tree(
        _agent("funfact", "weak"), tmp_path, agent_component_id="funfact",
    )
    assert out.system_prompt == "TREE-BRANCH"


# ---- resolver unit (precedence directly) ------------------------------


def test_resolver_returns_none_when_neither_exists(tmp_path: Path) -> None:
    assert find_promoted_snapshot_with_branch("funfact", tmp_path) is None


def test_resolver_returns_branch_when_only_branch(tmp_path: Path) -> None:
    _promote(tmp_path, "branch:funfact", "B", score_floor=0.5)
    snap = find_promoted_snapshot_with_branch("funfact", tmp_path)
    assert snap is not None
    assert snap.version.component_id == "branch:funfact"
