"""ComponentVersion — lineage-tracked snapshots of agent / tool / skill defs.

The improvement loop mutates definitions, compiles candidates, scores
them, and keeps winners. Each candidate is one ComponentVersion with:

- content_hash: sha256 of the canonical JSON form of the definition
- parent_hash: the version this one was mutated from (None for roots)
- timestamp + author (human / mutator name)
- definition: model_dump() of the underlying Agent/Tool/Skill/Prompt
- metrics: aggregated measurements pulled from JSONL test artifacts

The registry supports:

- register(version) — adds a node; rejects duplicate content_hash
- history(component_id) — every version of one logical component
  (agent_name / tool_name / skill_name / prompt-target) in chronological
  order
- ancestors(version) — walk the parent_hash chain back to the root
- by_metric(component_id, metric_name) — sorted by metric value
- diff(a, b) — list of (jsonpath, before, after) for content-level diff

Storage is in-memory by default. Phase 6.6's snapshot emitter persists
nodes as JSON files under improvements/<component>/<version_hash>.json.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ComponentKind = Literal["agent", "tool", "skill", "prompt"]


def _canonical_definition(definition: Any) -> dict[str, Any]:
    """Return a deep, JSON-normalized copy of a definition dict/model.

    This is the single source of truth for what a ComponentVersion *stores*
    and what gets hashed. Normalizing matters because callers pass definitions
    produced by ``model_dump()`` (which keeps tuples, and whose nested dicts /
    lists are shared, mutable objects) as well as raw dicts. Two problems
    follow from storing those directly:

    1. **Shared mutable substructure.** ``of(definition=parent.definition)``
       used to shallow-copy, so a child version aliased the parent's nested
       lists/dicts. Any in-place mutation of one (anywhere downstream — a
       mutator, an invoker compiling a candidate) silently changed the other's
       ``definition`` *after* its ``content_hash`` was computed, leaving a stale
       hash that only blows up later at snapshot/promote write time
       ("content_hash for ... does not match stable_content_hash(definition)").
    2. **tuple vs list ambiguity.** A tuple and a list hash the same here but
       reload from JSON as a list, so an in-memory version and its on-disk
       reload could disagree on type.

    Round-tripping through JSON deep-copies the structure (no aliasing) and
    coerces it to JSON-native types (tuples→lists), so the value we hash is
    byte-for-byte the value we store and later reload. ``sort_keys`` +
    ``default=str`` keep the canonical form deterministic.
    """
    if isinstance(definition, BaseModel):
        return json.loads(definition.model_dump_json())
    return json.loads(json.dumps(dict(definition), default=str))


def stable_content_hash(definition: Any) -> str:
    """sha256 over canonical JSON of the definition.

    Accepts dicts or Pydantic models. Sorts keys + uses str fallback so
    the hash is deterministic regardless of attribute insertion order.
    Hashes the *canonical* (deep, JSON-normalized) form so the hash matches
    what ``ComponentVersion.of`` stores — see :func:`_canonical_definition`.
    """
    payload = _canonical_definition(definition)
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ComponentVersion(BaseModel):
    """One frozen snapshot of an Agent / Tool / Skill / Prompt definition."""

    model_config = ConfigDict(frozen=True)

    component_id: str = Field(
        ..., description="Logical id (agent slug / tool name / skill name).",
    )
    kind: ComponentKind
    content_hash: str
    parent_hash: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"),
    )
    author: str = Field(
        default="human",
        description="'human' for source-authored, or the mutator name.",
    )
    definition: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    notes: str = ""

    def definition_copy(self) -> dict[str, Any]:
        """A deep, JSON-native copy of ``definition`` safe to hand to consumers.

        The loop/evaluators pass a candidate's definition to consumer callbacks
        (a mutator, a live invoker that compiles the candidate). If a callback
        mutates that dict in place — even one of its nested objects — it would
        staleify this frozen version's ``content_hash`` and blow up at
        snapshot/promote-write time. Always pass ``definition_copy()`` across
        that boundary so a consumer can never corrupt a stored version.
        """
        return _canonical_definition(self.definition)

    @model_validator(mode="after")
    def _content_hash_matches_definition(self) -> "ComponentVersion":
        if self.definition and self.content_hash != stable_content_hash(
            self.definition
        ):
            raise ValueError(
                f"content_hash for {self.component_id!r} does not match"
                " stable_content_hash(definition). Construct via"
                " ComponentVersion.of(...) to avoid this."
            )
        return self

    @classmethod
    def of(
        cls,
        component_id: str,
        kind: ComponentKind,
        definition: Any,
        *,
        parent_hash: str | None = None,
        author: str = "human",
        metrics: dict[str, float] | None = None,
        notes: str = "",
        timestamp: str | None = None,
    ) -> "ComponentVersion":
        """Build a ComponentVersion from a raw definition, hashing it for you.

        The definition is deep-copied into its canonical JSON-native form, so
        the stored ``definition`` is exactly what ``content_hash`` is computed
        over and is never aliased to the caller's (or a parent version's)
        mutable structure. This is what prevents a later in-place mutation from
        leaving a stale ``content_hash`` that fails at snapshot/promote time.
        """
        payload = _canonical_definition(definition)
        chash = stable_content_hash(payload)
        return cls(
            component_id=component_id,
            kind=kind,
            content_hash=chash,
            parent_hash=parent_hash,
            timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
            author=author,
            definition=payload,
            metrics=metrics or {},
            notes=notes,
        )


class ComponentRegistry(BaseModel):
    """In-memory store of every ComponentVersion the loop has seen."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _by_hash: dict[str, ComponentVersion] = {}
    _by_component: dict[str, list[str]] = {}

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # Reset class-level mutable defaults so each instance has its own
        # storage (Pydantic v2 reuses dict defaults otherwise).
        object.__setattr__(self, "_by_hash", {})
        object.__setattr__(self, "_by_component", {})

    def register(self, version: ComponentVersion) -> None:
        if version.content_hash in self._by_hash:
            raise ValueError(
                f"content_hash {version.content_hash[:8]}… already registered"
                f" for component {self._by_hash[version.content_hash].component_id!r}"
            )
        if version.parent_hash and version.parent_hash not in self._by_hash:
            raise ValueError(
                f"parent_hash {version.parent_hash[:8]}… not in registry —"
                f" register the parent first"
            )
        self._by_hash[version.content_hash] = version
        self._by_component.setdefault(version.component_id, []).append(
            version.content_hash
        )

    def get(self, content_hash: str) -> ComponentVersion | None:
        return self._by_hash.get(content_hash)

    def history(self, component_id: str) -> list[ComponentVersion]:
        """Chronological list of versions for one component."""
        hashes = self._by_component.get(component_id, [])
        return sorted(
            (self._by_hash[h] for h in hashes),
            key=lambda v: v.timestamp,
        )

    def ancestors(self, content_hash: str) -> list[ComponentVersion]:
        """Walk parent_hash chain back to the root. Newest first."""
        out: list[ComponentVersion] = []
        cursor = self._by_hash.get(content_hash)
        while cursor is not None:
            out.append(cursor)
            if cursor.parent_hash is None:
                break
            cursor = self._by_hash.get(cursor.parent_hash)
        return out

    def by_metric(
        self, component_id: str, metric: str, *, descending: bool = True,
    ) -> list[ComponentVersion]:
        history = [v for v in self.history(component_id) if metric in v.metrics]
        return sorted(
            history, key=lambda v: v.metrics[metric], reverse=descending,
        )

    def diff(self, a: str, b: str) -> list[dict[str, Any]]:
        """Field-level diff between two versions' definitions.

        Returns a list of {path: str, before: any, after: any} entries.
        Walks dicts recursively; lists compared element-wise by index.
        """
        va = self._by_hash.get(a)
        vb = self._by_hash.get(b)
        if va is None or vb is None:
            raise KeyError(
                f"unknown content_hash: a_present={va is not None},"
                f" b_present={vb is not None}"
            )
        return list(_walk_diff(va.definition, vb.definition, prefix=""))


def _walk_diff(a: Any, b: Any, *, prefix: str):
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        for k in sorted(keys):
            sub_prefix = f"{prefix}.{k}" if prefix else k
            yield from _walk_diff(a.get(k), b.get(k), prefix=sub_prefix)
        return
    if isinstance(a, list) and isinstance(b, list):
        max_len = max(len(a), len(b))
        for i in range(max_len):
            yield from _walk_diff(
                a[i] if i < len(a) else None,
                b[i] if i < len(b) else None,
                prefix=f"{prefix}[{i}]",
            )
        return
    yield {"path": prefix, "before": a, "after": b}
