"""Persist + reload ComponentVersions as JSON snapshots.

Snapshot layout under <root>/:

    <root>/
      <component_id>/
        <short_hash>.json    — one ComponentVersion serialized
        <short_hash>.json    — its sibling, etc.
        LATEST.json          — copy of the most recently written snapshot

`oac improve` writes round winners with write_round_winners(); `oac
promote` copies a snapshot into <project>/.oac/promoted/<component_id>.json
(or <component_id>__<slot>.json, where the slot is a model_class like
"fast" or a per-target key like "pi+fast" / "interactive" from
run_per_target_loops) so the user's agents/registry.py can pick it up
on next compile. Slot resolution at load time is
target → model_class → default within each bucket.

Per-client promotions (Phase A) live one directory deeper, under a
client bucket:
  <project>/.oac/promoted/<client_id>/<component_id>.json
(and <component_id>__<class>.json there too, since a client may still
tune per model class). client_id=None is the base bucket
(<project>/.oac/promoted/) — unchanged single-tenant behavior.

Resolution order at load time:
  client bucket  →  base bucket  →  None
and within whichever bucket is consulted, the existing per-class
fallback still applies:
  per-class file  →  default file
so callers always get something safely applicable when an improvement
exists, even if it's not tuned to the exact client/class they asked for.
"""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from open_agent_compiler.improvement.prompt_sections import apply_sections_to_definition
from open_agent_compiler.improvement.version import ComponentVersion, stable_content_hash

SNAPSHOT_SCHEMA_VERSION = "1"


class Snapshot(BaseModel):
    """On-disk format. Wraps a ComponentVersion + metadata for forward-compat."""

    model_config = ConfigDict(frozen=False)

    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    version: ComponentVersion
    notes: str = ""


def _component_dir(root: Path, component_id: str) -> Path:
    # Replace '/' so 'persona/orch' stays one directory deep.
    safe = component_id.replace("/", "__")
    return root / safe


def _filename(version: ComponentVersion) -> str:
    return f"{version.content_hash[:12]}.json"


def _promoted_filename(component_id: str, slot: str | None) -> str:
    """`<safe_id>.json` (default) or `<safe_id>__<slot>.json`.

    `slot` is either a model_class ("fast") or a target key
    ("pi+fast", "interactive") — both use the same filename shape, so
    per-target and per-class promotions coexist in one bucket.
    """
    safe = component_id.replace("/", "__")
    if slot:
        return f"{safe}__{slot}.json"
    return f"{safe}.json"


def _safe_client(client_id: str) -> str:
    """Sanitize a client_id for use as a single directory segment."""
    return client_id.replace("/", "__")


def _promoted_dir(project_root: Path, client_id: str | None) -> Path:
    """The `.oac/promoted/` bucket for `client_id`.

    client_id=None → the base bucket `<root>/.oac/promoted/` (today's
    single-tenant layout). A client bucket lives one level deeper at
    `<root>/.oac/promoted/<client_id>/`, mirroring how `model_class`
    selects a filename within a bucket — client_id selects the bucket.
    """
    base = project_root / ".oac" / "promoted"
    if client_id:
        return base / _safe_client(client_id)
    return base


def write_snapshot(
    version: ComponentVersion, root: Path, *, notes: str = "",
) -> Path:
    """Write one ComponentVersion to <root>/<component_id>/<short>.json."""
    dir_path = _component_dir(root, version.component_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / _filename(version)
    snap = Snapshot(version=version, notes=notes)
    path.write_text(snap.model_dump_json(indent=2))
    # Update LATEST.json for convenience lookups.
    latest = dir_path / "LATEST.json"
    latest.write_text(snap.model_dump_json(indent=2))
    return path


def write_round_winners(
    winners: list[ComponentVersion], root: Path, *, run_label: str = "",
) -> list[Path]:
    """Persist a loop's winners. Returns paths written, in order."""
    paths: list[Path] = []
    for v in winners:
        note = f"oac improve run={run_label!r}" if run_label else ""
        paths.append(write_snapshot(v, root, notes=note))
    return paths


def read_snapshot(path: Path) -> Snapshot:
    return Snapshot.model_validate_json(path.read_text())


def _read_promoted_tolerant(path: Path) -> Snapshot | None:
    """Read a *promoted* snapshot, tolerating a corrupt/legacy file.

    Promoted snapshots are consulted on every compile (via
    ``apply_promoted_to_*``). A single corrupt promotion — e.g. a stale-hash
    file written by an older build whose ``ComponentVersion.of`` aliased
    definitions — must NOT crash the whole compile/fleet; it should degrade to
    "no promotion" so the baseline passes through unchanged. A loud warning
    points the operator at the bad file so they can re-promote it. Explicit
    ``read_snapshot`` stays strict; only the resolution path is forgiving.
    """
    try:
        return read_snapshot(path)
    except Exception as exc:  # noqa: BLE001 - degrade, don't sink the compile
        healed = _heal_stale_hash(path)
        if healed is not None:
            warnings.warn(
                f"auto-healed stale-hash promoted snapshot {path}: recomputed"
                " content_hash from the intact definition and applied the"
                " improvement (file left untouched; re-promote to persist).",
                RuntimeWarning,
                stacklevel=2,
            )
            return healed
        warnings.warn(
            f"ignoring corrupt promoted snapshot {path}: {exc}."
            " Re-promote it to restore the improvement; the baseline is used"
            " until then.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def _heal_stale_hash(path: Path) -> Snapshot | None:
    """Recompute a promoted snapshot's ``content_hash`` from its INTACT definition.

    A stale-but-intact promotion (bookkeeping residue from an older build whose
    ``ComponentVersion.of`` aliased nested objects) would otherwise be dropped to
    baseline — silently losing real tuning. If the ``definition`` is present and
    the snapshot validates once its hash is recomputed, return that repaired
    snapshot (in-memory; the file is left untouched). Anything else (malformed
    JSON, missing/garbage definition) → ``None`` so the caller degrades safely.
    """
    try:
        raw = json.loads(path.read_text())
        version = raw.get("version")
        if not isinstance(version, dict) or not isinstance(
            version.get("definition"), dict
        ):
            return None
        version = dict(version)
        version["content_hash"] = stable_content_hash(version["definition"])
        healed = dict(raw)
        healed["version"] = version
        return Snapshot.model_validate(healed)
    except Exception:  # noqa: BLE001 - if it can't cleanly heal, degrade to None
        return None


def load_latest(root: Path, component_id: str) -> Snapshot | None:
    latest = _component_dir(root, component_id) / "LATEST.json"
    if not latest.exists():
        return None
    return read_snapshot(latest)


def list_snapshots(root: Path, component_id: str) -> list[Path]:
    """All snapshot files for one component, sorted by hash filename."""
    dir_path = _component_dir(root, component_id)
    if not dir_path.exists():
        return []
    return sorted(
        p for p in dir_path.glob("*.json") if p.name != "LATEST.json"
    )


def promote(
    snapshot_path: Path,
    project_root: Path,
    *,
    force: bool = False,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
) -> Path:
    """Copy a snapshot into the project's `.oac/promoted/` so a registry
    factory can pick it up on next compile.

    Without `model_class`/`target`, writes the default slot:
        <project_root>/.oac/promoted/<safe_id>.json
    With `model_class`, writes a class-specific slot:
        <project_root>/.oac/promoted/<safe_id>__<class>.json
    With `target` (a per-target loop key like "pi+fast" or
    "interactive"), writes the target slot — takes precedence over
    `model_class` when both are given:
        <project_root>/.oac/promoted/<safe_id>__<target>.json

    `client_id` selects a per-client bucket one directory deeper:
        <project_root>/.oac/promoted/<client_id>/<safe_id>.json
    (combinable with `model_class` for a per-client per-class slot).
    client_id=None writes the base bucket — unchanged behavior.

    Refuses to overwrite an existing promotion unless force=True so
    accidental promotions of older snapshots don't clobber newer ones.
    """
    snap = read_snapshot(snapshot_path)
    promoted_dir = _promoted_dir(project_root, client_id)
    promoted_dir.mkdir(parents=True, exist_ok=True)
    dest = promoted_dir / _promoted_filename(
        snap.version.component_id, target or model_class,
    )
    if dest.exists() and not force:
        raise FileExistsError(
            f"{dest} already exists; pass --force to overwrite"
        )
    shutil.copy(snapshot_path, dest)
    return dest


def _find_in_bucket(
    promoted_dir: Path, component_id: str, model_class: str | None,
    target: str | None = None,
) -> Snapshot | None:
    """Per-target > per-class > default > None fallback *within one bucket*.

    When `target` is provided (a per-target loop key like "pi+fast"),
    look first for `<safe_id>__<target>.json`. When `model_class` is
    provided, `<safe_id>__<class>.json` is next; then `<safe_id>.json`;
    then None. So a compile asking for a specific target gets the
    target-tuned winner when one was promoted, degrades to the
    class-tuned winner, and finally to the shared default.
    """
    for slot in (target, model_class):
        if not slot:
            continue
        slot_path = promoted_dir / _promoted_filename(component_id, slot)
        if slot_path.exists():
            hit = _read_promoted_tolerant(slot_path)
            if hit is not None:
                return hit
    default_path = promoted_dir / _promoted_filename(component_id, None)
    if default_path.exists():
        return _read_promoted_tolerant(default_path)
    return None


def find_promoted_snapshot(
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
) -> Snapshot | None:
    """Resolve a promoted snapshot with client → base → None fallback.

    When `client_id` is given, the client bucket
    `.oac/promoted/<client_id>/` is consulted first; if it yields
    nothing, the base bucket `.oac/promoted/` is tried. Within each
    bucket the slot fallback applies (per-target > per-class > default).
    client_id=None consults only the base bucket — unchanged behavior.

    Resolution order with all axes:
      <client>/<id>__<target> → <client>/<id>__<class> → <client>/<id>
      → <id>__<target> → <id>__<class> → <id> → None
    """
    root = project_root or Path.cwd()
    if client_id:
        client_hit = _find_in_bucket(
            _promoted_dir(root, client_id), component_id, model_class,
            target,
        )
        if client_hit is not None:
            return client_hit
    return _find_in_bucket(
        _promoted_dir(root, None), component_id, model_class, target,
    )


def load_promoted_snapshot(
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
) -> Snapshot | None:
    """Return the latest promoted Snapshot for `component_id`, or None.

    Thin alias of find_promoted_snapshot kept for backwards compatibility
    — older callers pass only (component_id, project_root) and get the
    default slot. Use find_promoted_snapshot directly when you need the
    per-class fallback chain documented in the module docstring.
    """
    return find_promoted_snapshot(
        component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )


def _branch_component_id(component_id: str) -> str:
    """The orchestrator-branch namespace for `component_id`.

    The per-branch (orchestrator) autoloop promotes its winner under
    ``branch:<entry>`` (see ``open_agent_compiler/improvement/branch.py``'s
    ``branch_component_id``). When applying improvements *for an agent*
    we also consider that branch-level promotion so a branched
    optimisation of an orchestrator actually lands at compile.
    """
    return f"branch:{component_id}"


def _snapshot_score(snap: Snapshot) -> float:
    """The comparable score recorded on a promoted snapshot.

    Prefers ``score_floor`` (the worst-path / weakest-criterion score the
    loop optimises against), falling back to ``pass_rate`` so older
    snapshots that only recorded a pass rate still compare. Missing both
    sorts lowest so a scored promotion always beats an unscored one.
    """
    metrics = snap.version.metrics
    if "score_floor" in metrics:
        return metrics["score_floor"]
    if "pass_rate" in metrics:
        return metrics["pass_rate"]
    return float("-inf")


def find_promoted_snapshot_with_branch(
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
) -> Snapshot | None:
    """Resolve a promotion for an agent, considering its ``branch:<id>`` twin.

    Resolves BOTH the agent's own id ``<id>`` and the orchestrator-branch
    id ``branch:<id>`` through the *same* client → base / per-class
    fallback machinery (:func:`find_promoted_snapshot`), then returns the
    one with the higher recorded score (``score_floor`` → ``pass_rate``).

    Precedence on a tie is the ``branch:<id>`` snapshot: it is
    outcome-judged on the full multi-step session, the more meaningful
    signal for an orchestrator than its own leaf-agent loop. If only one
    of the two exists, that one is returned; if neither exists, ``None``.

    This composes transparently with per-client buckets and per-class
    slots because each id is resolved through ``find_promoted_snapshot``
    independently — a client bucket may hold ``branch:<id>`` too.
    """
    own = find_promoted_snapshot(
        component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    branch = find_promoted_snapshot(
        _branch_component_id(component_id), project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    if branch is None:
        return own
    if own is None:
        return branch
    # Both exist: higher score wins; tie → prefer the branch promotion.
    if _snapshot_score(branch) >= _snapshot_score(own):
        return branch
    return own


def load_promoted_definition(
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
) -> dict | None:
    """Return just the promoted ComponentVersion.definition dict, or None.

    Use in agents.py to merge an improved prompt back into a baseline
    without handling the full Snapshot envelope:

        baseline = AgentDefinition(... system_prompt="weak prompt" ...)
        promoted = load_promoted_definition("my-agent", project_root=HERE)
        if promoted and "system_prompt" in promoted:
            baseline = baseline.model_copy(
                update={"system_prompt": promoted["system_prompt"]}
            )

    Returns None when no promotion has been made yet, so the registry
    factory still works cleanly on a fresh project.
    """
    snap = find_promoted_snapshot(
        component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    if snap is None:
        return None
    return dict(snap.version.definition)


# ---- Per-kind apply helpers ------------------------------------------
#
# These let any composable piece (agent, tool, skill, full tree) point
# transparently at its auto-improved version: if a promotion exists, it
# is merged onto the baseline; otherwise the baseline passes through
# unchanged. This is the surface the user described as "each part of
# this structure can be replaced with auto-optimised version of itself".


_AGENT_FIELDS_DEFAULT: tuple[str, ...] = (
    "system_prompt", "preamble", "postamble", "todo_mode",
    "model_class",
    # Structured per-section prompt (open_agent_compiler.improvement.prompt_sections). When a
    # promoted snapshot carries it, the merged definition re-derives
    # system_prompt from the sections at compile time — so per-section autoloop
    # gains persist and the rich scaffold is promoted intact.
    "prompt_sections",
)

_TOOL_HEADER_FIELDS_DEFAULT: tuple[str, ...] = (
    "description", "usage_explanation_long", "usage_explanation_short",
    "rules",
)

_SKILL_FIELDS_DEFAULT: tuple[str, ...] = (
    "description", "usage_explanation_long", "usage_explanation_short",
    "rules",
)


def apply_promoted_to_agent(
    agent_definition,
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
    fields: tuple[str, ...] = _AGENT_FIELDS_DEFAULT,
    consider_branch: bool = True,
):
    """Merge selected fields from a promoted definition onto an AgentDefinition.

    No-op when no promotion exists. Only the named fields are merged
    (default: prompt-related + model_class); structural state on
    `agent_definition` (subagents, tools, permissions, …) is preserved
    so a single registry helper can apply improvements safely.

    `model_class` selects the per-class slot with a fallback to the
    default slot; pass the agent's intended model class to pick the
    right snapshot when class-specific tuning was promoted.

    `target` selects a per-target slot (a `run_per_target_loops` key
    like "pi+fast" or "interactive") with the highest precedence —
    pass the target the compile is for so a harness+model-specific
    winner is applied when one was promoted, falling back to the
    per-class and then the default slot.

    `client_id` selects the per-client bucket with a fallback to the
    base bucket — a client's compile reads its own promotions, falling
    back to the shared base when the client hasn't tuned this component.

    `consider_branch` (default True) also resolves the orchestrator-branch
    promotion ``branch:<component_id>`` and applies whichever of the two
    has the higher recorded score (tie → the branch promotion) — see
    :func:`find_promoted_snapshot_with_branch`. The per-branch autoloop
    promotes an improved orchestrator under ``branch:<entry>``; this is
    what makes that improvement actually land at compile. Set False to
    restrict resolution to the component's own id (used when applying to a
    component that is itself looked up by a ``branch:`` id, to avoid a
    ``branch:branch:`` double lookup).
    """
    if consider_branch:
        snap = find_promoted_snapshot_with_branch(
            component_id, project_root,
            model_class=model_class, client_id=client_id, target=target,
        )
        promoted = dict(snap.version.definition) if snap is not None else None
    else:
        promoted = load_promoted_definition(
            component_id, project_root,
            model_class=model_class, client_id=client_id, target=target,
        )
    if not promoted:
        return agent_definition
    updates = {f: promoted[f] for f in fields if f in promoted}
    if not updates:
        return agent_definition
    merged = agent_definition.model_copy(update=updates)
    # If the merged definition carries prompt_sections, re-derive
    # system_prompt from them so per-section autoloop gains persist.
    merged_dict = merged.model_dump()
    if "prompt_sections" in merged_dict and merged_dict["prompt_sections"]:
        derived = apply_sections_to_definition(merged_dict)
        merged = merged.model_copy(update={"system_prompt": derived["system_prompt"]})
    return merged


def apply_promoted_to_tool(
    tool_definition,
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
    header_fields: tuple[str, ...] = _TOOL_HEADER_FIELDS_DEFAULT,
):
    """Merge promoted-header fields onto a ToolDefinition.

    The improvement loop mutates a tool's *description* / *rules* /
    *usage explanation* — fields under `tool.header`. This helper reads
    matching keys from the promoted definition dict and rebuilds the
    header with them overlaid. No-op when no promotion exists.

    `client_id` selects the per-client bucket (fallback to base);
    `model_class` the per-class slot within the chosen bucket.

    Structural state (json_tool, bash_tool, requires_resources, tool
    scripts) is preserved.
    """
    promoted = load_promoted_definition(
        component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    if not promoted:
        return tool_definition
    header_updates = {f: promoted[f] for f in header_fields if f in promoted}
    if not header_updates:
        return tool_definition
    new_header = tool_definition.header.model_copy(update=header_updates)
    return tool_definition.model_copy(update={"header": new_header})


def apply_promoted_to_skill(
    skill_definition,
    component_id: str,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
    fields: tuple[str, ...] = _SKILL_FIELDS_DEFAULT,
):
    """Merge promoted-skill fields onto a SkillDefinition.

    SkillDefinition holds description / rules / usage explanations at
    the top level (no header wrapper), so we update them directly.
    workflow_steps and examples are preserved. `client_id` selects the
    per-client bucket (fallback to base); `model_class` the per-class slot.
    """
    promoted = load_promoted_definition(
        component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    if not promoted:
        return skill_definition
    updates = {f: promoted[f] for f in fields if f in promoted}
    if not updates:
        return skill_definition
    return skill_definition.model_copy(update=updates)


def _apply_promoted_to_skill_tools(
    skill, project_root: Path | None, model_class: str | None,
    client_id: str | None = None, target: str | None = None,
):
    """Walk a skill's workflow_steps + examples, applying tool promotions.

    Tools are referenced from three places on a SkillDefinition:
        - workflow_steps[].tools_used
        - positive_examples[].tools_used
        - negative_examples[].tools_used
    Each list holds ToolDefinitions; each carries its own component
    name (`tool.header.name`) and so picks up its own promoted
    snapshot independently. Tools appearing in multiple places get the
    same merge applied to each reference (idempotent — model_copy
    with the same fields produces equivalent values).
    """
    def _walk_steps(steps):
        return [
            step.model_copy(update={
                "tools_used": [
                    apply_promoted_to_tool(
                        t, t.header.name, project_root,
                        model_class=model_class, client_id=client_id,
                        target=target,
                    ) for t in step.tools_used
                ],
            }) if step.tools_used else step
            for step in steps
        ]
    new_skill = skill.model_copy(update={
        "workflow_steps": _walk_steps(skill.workflow_steps),
        "positive_examples": _walk_steps(skill.positive_examples),
        "negative_examples": _walk_steps(skill.negative_examples),
    })
    return new_skill


def apply_promoted_to_tree(
    agent_definition,
    project_root: Path | None = None,
    *,
    model_class: str | None = None,
    client_id: str | None = None,
    target: str | None = None,
    agent_component_id: str | None = None,
):
    """Apply promoted improvements across an entire AgentDefinition tree.

    Walks (in order):
      1. The agent itself — `agent_component_id` or
         `agent_definition.header.agent_id` is used as the lookup key.
      2. Each `SkillDefinition` in `agent_definition.skills` — keyed
         by the skill's `name`.
      3. Each `ToolDefinition` reachable through every skill — both
         via `workflow_steps[].tools_used` and via
         positive/negative example `tools_used`.
      4. Each `ToolDefinition` in `agent_definition.extra_tools` —
         keyed by the tool's `header.name`.

    Subagents are AgentHeader references (not full definitions), so
    they are not walked here — they are improved when registered in
    their own right via `register_with_improvements` on the registry.

    `client_id`, when set, reads each component from the client's
    promotion bucket first and falls back to the shared base bucket —
    so a per-client compile transparently picks up client-tuned parts
    and inherits base-tuned parts for everything the client hasn't
    personalized.

    The composable promise: if any individual part has been
    auto-iterated and promoted, it loads; everything else passes
    through unchanged.
    """
    component_id = agent_component_id or agent_definition.header.agent_id
    out = apply_promoted_to_agent(
        agent_definition, component_id, project_root,
        model_class=model_class, client_id=client_id, target=target,
    )
    if out.skills:
        new_skills = []
        for s in out.skills:
            improved = apply_promoted_to_skill(
                s, s.name, project_root,
                model_class=model_class, client_id=client_id, target=target,
            )
            improved = _apply_promoted_to_skill_tools(
                improved, project_root, model_class, client_id, target,
            )
            new_skills.append(improved)
        out = out.model_copy(update={"skills": new_skills})
    if out.extra_tools:
        new_tools = [
            apply_promoted_to_tool(
                t, t.header.name, project_root,
                model_class=model_class, client_id=client_id, target=target,
            )
            for t in out.extra_tools
        ]
        out = out.model_copy(update={"extra_tools": new_tools})
    return out
