"""Snapshot emitter + oac promote CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_agent_compiler.cli.main import main as cli_main
from open_agent_compiler.improvement.snapshot import (
    apply_promoted_to_agent,
    apply_promoted_to_skill,
    apply_promoted_to_tool,
    apply_promoted_to_tree,
    find_promoted_snapshot,
    list_snapshots,
    load_latest,
    promote,
    read_snapshot,
    write_round_winners,
    write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion


def _version(prompt: str = "v1", parent: str | None = None) -> ComponentVersion:
    return ComponentVersion.of(
        component_id="persona/orch", kind="agent",
        definition={"name": "orch", "system_prompt": prompt},
        parent_hash=parent,
        metrics={"pass_rate": 0.9},
    )


def test_write_snapshot_creates_dir_and_file(tmp_path: Path) -> None:
    v = _version()
    out = write_snapshot(v, tmp_path / "improved")
    assert out.exists()
    # Component dir uses __-separated paths instead of /
    assert out.parent.name == "persona__orch"
    # LATEST.json mirrors the snapshot.
    latest = out.parent / "LATEST.json"
    assert latest.exists()
    assert latest.read_text() == out.read_text()


def test_snapshot_roundtrip_preserves_metrics_and_lineage(tmp_path: Path) -> None:
    parent_v = _version("v0")
    child_v = _version("v1", parent=parent_v.content_hash)
    path = write_snapshot(child_v, tmp_path / "improved")
    snap = read_snapshot(path)
    assert snap.version.parent_hash == parent_v.content_hash
    assert snap.version.metrics == {"pass_rate": 0.9}
    assert snap.schema_version == "1"


def test_write_round_winners_writes_each(tmp_path: Path) -> None:
    v1 = _version("v1")
    v2 = _version("v2", parent=v1.content_hash)
    paths = write_round_winners([v1, v2], tmp_path / "imp", run_label="round-3")
    assert len(paths) == 2
    for p in paths:
        snap = read_snapshot(p)
        assert "round-3" in snap.notes


def test_list_snapshots_excludes_latest(tmp_path: Path) -> None:
    root = tmp_path / "imp"
    v1 = _version("v1")
    v2 = _version("v2", parent=v1.content_hash)
    write_snapshot(v1, root)
    write_snapshot(v2, root)
    listing = list_snapshots(root, "persona/orch")
    assert len(listing) == 2
    assert all(p.name != "LATEST.json" for p in listing)


def test_load_latest_returns_most_recent_write(tmp_path: Path) -> None:
    root = tmp_path / "imp"
    v1 = _version("v1")
    v2 = _version("v2", parent=v1.content_hash)
    write_snapshot(v1, root)
    write_snapshot(v2, root)
    latest = load_latest(root, "persona/orch")
    assert latest is not None
    assert latest.version.definition["system_prompt"] == "v2"


def test_load_latest_none_when_no_snapshots(tmp_path: Path) -> None:
    assert load_latest(tmp_path, "no-such-thing") is None


# ---- promote --------------------------------------------------------


def test_promote_copies_to_oac_promoted(tmp_path: Path) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    dest = promote(snap_path, project)
    assert dest == project / ".oac" / "promoted" / "persona__orch.json"
    assert dest.exists()
    # Contents identical.
    assert dest.read_text() == snap_path.read_text()


def test_promote_refuses_overwrite_without_force(tmp_path: Path) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    promote(snap_path, project)
    with pytest.raises(FileExistsError):
        promote(snap_path, project)


def test_promote_force_overwrites(tmp_path: Path) -> None:
    v1 = _version("v1")
    v2 = _version("v2", parent=v1.content_hash)
    root = tmp_path / "imp"
    write_snapshot(v1, root)
    path2 = write_snapshot(v2, root)
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(v1, root), project)
    promote(path2, project, force=True)
    promoted = (project / ".oac" / "promoted" / "persona__orch.json").read_text()
    assert "v2" in promoted


# ---- CLI -----------------------------------------------------------


def test_cli_promote_writes_to_oac_promoted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    rc = cli_main([
        "promote", str(snap_path),
        "--project", str(project),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "promote" in out
    assert (project / ".oac" / "promoted" / "persona__orch.json").exists()


def test_cli_promote_show_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    rc = cli_main([
        "promote", str(snap_path),
        "--project", str(project),
        "--show",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Metrics:" in out
    assert not (project / ".oac" / "promoted").exists()


def test_cli_promote_handles_existing_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    cli_main(["promote", str(snap_path), "--project", str(project)])
    capsys.readouterr()
    rc = cli_main(["promote", str(snap_path), "--project", str(project)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "already exists" in out


# ---- per-class promote + resolver ----------------------------------


def test_promote_with_class_writes_class_suffixed_file(tmp_path: Path) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    dest = promote(snap_path, project, model_class="fast")
    assert dest.name == "persona__orch__fast.json"
    assert dest.exists()


def test_find_promoted_class_overrides_default(tmp_path: Path) -> None:
    """Per-class slot wins when present."""
    default_v = _version("default-prompt")
    class_v = _version("fast-prompt")
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(default_v, tmp_path / "imp1"), project)
    promote(
        write_snapshot(class_v, tmp_path / "imp2"), project,
        model_class="fast",
    )
    snap = find_promoted_snapshot(
        "persona/orch", project, model_class="fast",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "fast-prompt"


def test_find_promoted_class_falls_back_to_default(tmp_path: Path) -> None:
    """Default slot returned when no per-class file exists."""
    default_v = _version("default-prompt")
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(default_v, tmp_path / "imp"), project)
    snap = find_promoted_snapshot(
        "persona/orch", project, model_class="missing-class",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "default-prompt"


def test_find_promoted_returns_none_with_no_promotion(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    assert find_promoted_snapshot("persona/orch", project) is None
    assert find_promoted_snapshot(
        "persona/orch", project, model_class="fast",
    ) is None


def test_find_promoted_self_heals_stale_hash_legacy_file(tmp_path: Path) -> None:
    """A stale-hash promoted file with an INTACT definition self-heals.

    content_hash is a recomputable checksum, not a guarantee about the definition.
    A legacy stale-hash artifact (intact, parseable definition) is healed — the
    hash is recomputed and the improvement applied — rather than dropped to
    baseline, so real tuning isn't silently lost. A fleet compile that consults it
    via apply_promoted_to_* never crashes either way.
    """
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(_version("good"), tmp_path / "imp"), project)
    # Stale-hash legacy snapshot: definition intact, content_hash no longer matches.
    promoted_file = project / ".oac" / "promoted" / "persona__orch.json"
    blob = json.loads(promoted_file.read_text())
    blob["version"]["definition"]["system_prompt"] = "the-real-improved-prompt"
    promoted_file.write_text(json.dumps(blob))

    with pytest.warns(RuntimeWarning, match="auto-healed"):
        snap = find_promoted_snapshot("persona/orch", project)
    assert snap is not None  # healed + applied, not dropped
    assert snap.version.definition["system_prompt"] == "the-real-improved-prompt"


def test_promote_class_and_default_coexist(tmp_path: Path) -> None:
    """A default promotion plus a class-suffixed one live side by side."""
    project = tmp_path / "proj"
    project.mkdir()
    snap_default = write_snapshot(_version("default"), tmp_path / "a")
    snap_fast = write_snapshot(_version("fast"), tmp_path / "b")
    promote(snap_default, project)
    promote(snap_fast, project, model_class="fast")
    promoted_dir = project / ".oac" / "promoted"
    assert (promoted_dir / "persona__orch.json").exists()
    assert (promoted_dir / "persona__orch__fast.json").exists()


def test_cli_promote_with_class_flag_writes_suffixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    rc = cli_main([
        "promote", str(snap_path),
        "--project", str(project),
        "--class", "analytical",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert (
        project / ".oac" / "promoted" / "persona__orch__analytical.json"
    ).exists()
    assert "class=analytical" in out


# ---- per-client promote + resolver (Phase A) -----------------------


def test_promote_with_client_writes_to_client_bucket(tmp_path: Path) -> None:
    v = _version()
    snap_path = write_snapshot(v, tmp_path / "imp")
    project = tmp_path / "proj"
    project.mkdir()
    dest = promote(snap_path, project, client_id="acme")
    assert dest == (
        project / ".oac" / "promoted" / "acme" / "persona__orch.json"
    )
    assert dest.exists()


def test_per_client_snapshot_round_trip(tmp_path: Path) -> None:
    """Promote to a client bucket, read it back via the resolver."""
    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(_version("acme-prompt"), tmp_path / "imp"),
        project, client_id="acme",
    )
    snap = find_promoted_snapshot(
        "persona/orch", project, client_id="acme",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "acme-prompt"


def test_find_promoted_client_overrides_base(tmp_path: Path) -> None:
    """Client bucket wins over the shared base bucket when present."""
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(_version("base-prompt"), tmp_path / "a"), project)
    promote(
        write_snapshot(_version("acme-prompt"), tmp_path / "b"),
        project, client_id="acme",
    )
    snap = find_promoted_snapshot(
        "persona/orch", project, client_id="acme",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "acme-prompt"


def test_find_promoted_client_falls_back_to_base(tmp_path: Path) -> None:
    """Base bucket returned when the client has not tuned this component."""
    project = tmp_path / "proj"
    project.mkdir()
    promote(write_snapshot(_version("base-prompt"), tmp_path / "a"), project)
    snap = find_promoted_snapshot(
        "persona/orch", project, client_id="acme",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "base-prompt"


def test_find_promoted_client_then_base_then_none(tmp_path: Path) -> None:
    """Full resolution order: client → base → None."""
    project = tmp_path / "proj"
    project.mkdir()
    # Nothing promoted at all → None even with a client_id.
    assert find_promoted_snapshot(
        "persona/orch", project, client_id="acme",
    ) is None


def test_per_client_per_class_combine(tmp_path: Path) -> None:
    """client selects the bucket; model_class selects the slot within it."""
    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(_version("acme-fast"), tmp_path / "a"),
        project, client_id="acme", model_class="fast",
    )
    # Per-client per-class slot resolves.
    snap = find_promoted_snapshot(
        "persona/orch", project, client_id="acme", model_class="fast",
    )
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "acme-fast"
    # A different class under the same client falls back: client default
    # absent → base absent → None.
    assert find_promoted_snapshot(
        "persona/orch", project, client_id="acme", model_class="other",
    ) is None


def test_base_behavior_unchanged_when_client_id_none(tmp_path: Path) -> None:
    """client_id=None never looks inside a client bucket."""
    project = tmp_path / "proj"
    project.mkdir()
    # Only a client promotion exists; base lookup must NOT see it.
    promote(
        write_snapshot(_version("acme-only"), tmp_path / "a"),
        project, client_id="acme",
    )
    assert find_promoted_snapshot("persona/orch", project) is None
    assert find_promoted_snapshot(
        "persona/orch", project, client_id=None,
    ) is None


def test_two_clients_isolated_buckets(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(_version("acme"), tmp_path / "a"),
        project, client_id="acme",
    )
    promote(
        write_snapshot(_version("globex"), tmp_path / "b"),
        project, client_id="globex",
    )
    acme = find_promoted_snapshot("persona/orch", project, client_id="acme")
    globex = find_promoted_snapshot(
        "persona/orch", project, client_id="globex",
    )
    assert acme.version.definition["system_prompt"] == "acme"
    assert globex.version.definition["system_prompt"] == "globex"


def test_apply_promoted_to_agent_with_client(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(_version("acme-prompt"), tmp_path / "a"),
        project, client_id="acme",
    )
    agent = _make_agent_def("baseline")
    out = apply_promoted_to_agent(
        agent, "persona/orch", project, client_id="acme",
    )
    assert out.system_prompt == "acme-prompt"
    # Base build ignores the client bucket.
    base_out = apply_promoted_to_agent(agent, "persona/orch", project)
    assert base_out.system_prompt == "baseline"


def test_apply_promoted_to_tree_with_client(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    from open_agent_compiler.improvement.snapshot import apply_promoted_to_tree
    agent = _make_agent_def("baseline", agent_id="persona/orch")
    # Promote under the agent_id key in the client bucket.
    av = ComponentVersion.of(
        component_id="persona/orch", kind="agent",
        definition={"system_prompt": "acme-tree"},
    )
    promote(write_snapshot(av, tmp_path / "a"), project, client_id="acme")
    out = apply_promoted_to_tree(agent, project, client_id="acme")
    assert out.system_prompt == "acme-tree"


# ---- per-kind apply helpers ----------------------------------------


def _make_agent_def(
    prompt: str = "weak", agent_id: str = "persona/orch",
):
    from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
    return AgentDefinition(
        header=AgentHeader(
            agent_id=agent_id, name=agent_id, description=None,
        ),
        usage_explanation_long="l",
        usage_explanation_short="s",
        system_prompt=prompt,
    )


def test_apply_promoted_to_agent_with_class(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(_version("class-fast"), tmp_path / "a"),
        project, model_class="fast",
    )
    agent = _make_agent_def("baseline")
    out = apply_promoted_to_agent(
        agent, "persona/orch", project, model_class="fast",
    )
    assert out.system_prompt == "class-fast"


def test_apply_promoted_to_tool_updates_header_fields(tmp_path: Path) -> None:
    """Promoted definition merges into ToolDefinition.header."""
    from open_agent_compiler.improvement.version import ComponentVersion
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
    )

    project = tmp_path / "proj"
    project.mkdir()
    tool_version = ComponentVersion.of(
        component_id="tools/echo", kind="tool",
        definition={
            "name": "echo",
            "description": "Improved echo tool description.",
            "rules": ["follow rule A"],
        },
        metrics={},
    )
    promote(write_snapshot(tool_version, tmp_path / "a"), project)

    baseline = ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo",
            description="Old description.",
            usage_explanation_long="long",
            usage_explanation_short="short",
            rules=[],
        ),
    )
    improved = apply_promoted_to_tool(baseline, "tools/echo", project)
    assert improved.header.description == "Improved echo tool description."
    assert improved.header.rules == ["follow rule A"]
    # Name preserved (wasn't in default header_fields).
    assert improved.header.name == "echo"


def test_apply_promoted_to_tool_noop_without_promotion(tmp_path: Path) -> None:
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
    )
    baseline = ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo", description="d", usage_explanation_long="l",
            usage_explanation_short="s", rules=[],
        ),
    )
    out = apply_promoted_to_tool(baseline, "tools/echo", tmp_path / "proj")
    assert out is baseline


def test_apply_promoted_to_skill_merges_top_level(tmp_path: Path) -> None:
    from open_agent_compiler.improvement.version import ComponentVersion
    from open_agent_compiler.model.core.skills_model import SkillDefinition

    project = tmp_path / "proj"
    project.mkdir()
    sv = ComponentVersion.of(
        component_id="skills/summarize", kind="skill",
        definition={
            "name": "summarize",
            "description": "Improved summarize description.",
            "rules": ["use short sentences"],
        },
        metrics={},
    )
    promote(write_snapshot(sv, tmp_path / "a"), project)

    baseline = SkillDefinition(
        name="summarize",
        description="Old description.",
        usage_explanation_long="l",
        usage_explanation_short="s",
        rules=[],
        workflow_steps=[],
        positive_examples=[],
        negative_examples=[],
    )
    improved = apply_promoted_to_skill(baseline, "skills/summarize", project)
    assert improved.description == "Improved summarize description."
    assert improved.rules == ["use short sentences"]


def test_apply_promoted_to_tree_walks_agent_plus_skills_plus_tools(
    tmp_path: Path,
) -> None:
    """One call applies promotions across the whole composable tree."""
    from open_agent_compiler.improvement.version import ComponentVersion
    from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
    from open_agent_compiler.model.core.skills_model import SkillDefinition
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
    )

    project = tmp_path / "proj"
    project.mkdir()
    # Promote agent, one skill, and one tool — each independently.
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="agent-x", kind="agent",
                definition={"system_prompt": "agent-improved"},
                metrics={},
            ),
            tmp_path / "a",
        ),
        project,
    )
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="skill-x", kind="skill",
                definition={"description": "skill-improved"},
                metrics={},
            ),
            tmp_path / "b",
        ),
        project,
    )
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="tool-x", kind="tool",
                definition={"description": "tool-improved"},
                metrics={},
            ),
            tmp_path / "c",
        ),
        project,
    )

    skill = SkillDefinition(
        name="skill-x", description="old-skill",
        usage_explanation_long="l", usage_explanation_short="s",
        rules=[], workflow_steps=[],
        positive_examples=[], negative_examples=[],
    )
    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="tool-x", description="old-tool",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[],
        ),
    )
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="agent-x", name="agent-x", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="old-agent",
        skills=[skill], extra_tools=[tool],
    )
    improved = apply_promoted_to_tree(agent, project)
    assert improved.system_prompt == "agent-improved"
    assert improved.skills[0].description == "skill-improved"
    assert improved.extra_tools[0].header.description == "tool-improved"


def test_apply_promoted_to_tree_noop_when_nothing_promoted(
    tmp_path: Path,
) -> None:
    """Tree returns identity when nothing has been promoted."""
    from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="fresh", name="fresh", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="baseline",
    )
    out = apply_promoted_to_tree(agent, tmp_path / "proj")
    assert out is agent


def test_apply_promoted_to_tree_reaches_tools_inside_skill_workflow(
    tmp_path: Path,
) -> None:
    """Tools nested under skill.workflow_steps[].tools_used get improved."""
    from open_agent_compiler.improvement.version import ComponentVersion
    from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
    from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
    )

    project = tmp_path / "proj"
    project.mkdir()
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="nested-tool", kind="tool",
                definition={"description": "promoted-tool-desc"},
                metrics={},
            ),
            tmp_path / "imp",
        ),
        project,
    )

    tool = ToolDefinition(
        header=ToolDefinitionHeader(
            name="nested-tool", description="old-desc",
            usage_explanation_long="l", usage_explanation_short="s",
            rules=[],
        ),
    )
    skill = SkillDefinition(
        name="skill-x", description="d",
        usage_explanation_long="l", usage_explanation_short="s",
        rules=[],
        workflow_steps=[
            WorkflowStep(
                header="step", condition=None, result=None, rule=None,
                tools_used=[tool],
            ),
        ],
        positive_examples=[], negative_examples=[],
    )
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="agent-y", name="agent-y", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        skills=[skill],
    )
    improved = apply_promoted_to_tree(agent, project)
    nested = improved.skills[0].workflow_steps[0].tools_used[0]
    assert nested.header.description == "promoted-tool-desc"


def test_tolerant_loader_self_heals_stale_hash(tmp_path: Path) -> None:
    """A promoted snapshot with an INTACT definition but a stale content_hash is
    auto-healed (hash recomputed) and applied — not silently dropped to baseline."""
    project = tmp_path / "proj"
    v = _version("the improved prompt")
    promote(write_snapshot(v, tmp_path / "snaps"), project)
    pf = next((project / ".oac" / "promoted").glob("persona*.json"))
    raw = json.loads(pf.read_text())
    raw["version"]["content_hash"] = "0" * 64  # stale, definition untouched
    pf.write_text(json.dumps(raw))
    with pytest.warns(RuntimeWarning, match="auto-healed"):
        snap = find_promoted_snapshot("persona/orch", project)
    assert snap is not None
    assert snap.version.definition["system_prompt"] == "the improved prompt"


def test_tolerant_loader_drops_unrecoverable_promotion(tmp_path: Path) -> None:
    """A genuinely broken promotion (no usable definition) still degrades to None."""
    project = tmp_path / "proj"
    v = _version("x")
    promote(write_snapshot(v, tmp_path / "snaps"), project)
    pf = next((project / ".oac" / "promoted").glob("persona*.json"))
    pf.write_text("{ not valid json")
    with pytest.warns(RuntimeWarning, match="ignoring corrupt"):
        assert find_promoted_snapshot("persona/orch", project) is None
