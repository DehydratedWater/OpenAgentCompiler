"""profile_datasource — enumerate a source, sample it, infer conventions.

`profile_datasource(adapter)` drives a `DatasourceAdapter` through
`connect -> enumerate_structure -> sample`, then runs pure heuristics over
the result to INFER:

  * the folder/container layout (top-level groups, depth, container count),
  * the file/leaf type distribution (which extensions/types dominate),
  * naming conventions (snake_case / kebab-case / dated prefixes / …),
  * where the relevant data likely lives (the densest leaf-bearing
    containers), and
  * a human-readable `summary` string suitable for injection into an
    agent's prompt so the agent KNOWS the client's structure.

The result is a frozen Pydantic `DatasourceProfile`. `context_block()`
turns its `summary` into a `ContextBlock` (the Phase E injection seam).

All inference is deterministic and offline — given the same structure +
sample it always produces the same profile, which is what tests assert.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.context_blocks import ContextBlock

if TYPE_CHECKING:
    from open_agent_compiler.datasource.adapter import (
        DatasourceAdapter,
        DatasourceItem,
        DatasourceStructure,
    )

# Naming-convention labels the heuristics can detect on leaf basenames.
NamingConvention = str  # one of the _CONVENTIONS keys, or "mixed"/"unknown"

_DATED_PREFIX = re.compile(r"^\d{4}[-_]?\d{2}([-_]?\d{2})?[-_ ]")
_SNAKE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)+$")
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
_CAMEL = re.compile(r"^[a-z]+([A-Z][a-z0-9]*)+$")


def _stem(name: str) -> str:
    """Strip a trailing extension for naming-convention checks."""
    if "." in name and not name.startswith("."):
        return name.rsplit(".", 1)[0]
    return name


def _classify_name(name: str) -> str:
    stem = _stem(name)
    if _DATED_PREFIX.match(name) or _DATED_PREFIX.match(stem):
        return "dated_prefix"
    if _SNAKE.match(stem):
        return "snake_case"
    if _KEBAB.match(stem):
        return "kebab-case"
    if _CAMEL.match(stem):
        return "camelCase"
    return "freeform"


def _top_level(path: str, root: str) -> str | None:
    """Return the first path segment beneath `root`, or None for the root."""
    norm_root = root.rstrip("/")
    p = path
    if norm_root and p.startswith(norm_root):
        p = p[len(norm_root):]
    p = p.strip("/")
    if not p:
        return None
    return p.split("/")[0]


def _depth(path: str, root: str) -> int:
    norm_root = root.rstrip("/")
    p = path
    if norm_root and p.startswith(norm_root):
        p = p[len(norm_root):]
    p = p.strip("/")
    if not p:
        return 0
    return len(p.split("/"))


def _parent(path: str) -> str:
    p = path.rstrip("/")
    if "/" not in p:
        return "/"
    return p.rsplit("/", 1)[0] or "/"


class DatasourceProfile(BaseModel):
    """Inferred conventions + layout for one client datasource.

    Structured fields drive the derived-tool generation and let callers
    reason programmatically; `summary` is the human/agent-readable digest
    injected into the agent's context. `relevant_locations` lists the
    container paths where the bulk of leaf data lives (the agent should
    look there first). `naming_convention` is the dominant convention over
    leaf basenames. `file_types` maps a coarse type/extension → count.
    """

    model_config = ConfigDict(frozen=True)

    datasource_name: str
    kind: str = "other"
    root: str = "/"

    container_count: int = 0
    leaf_count: int = 0
    max_depth: int = 0
    truncated: bool = False

    top_level_groups: tuple[str, ...] = Field(
        default=(),
        description="First-level container names beneath the root.",
    )
    file_types: dict[str, int] = Field(
        default_factory=dict,
        description="Coarse leaf type/extension → count (descending).",
    )
    naming_convention: NamingConvention = Field(
        default="unknown",
        description="Dominant naming convention over leaf basenames.",
    )
    naming_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Convention label → leaf count.",
    )
    relevant_locations: tuple[str, ...] = Field(
        default=(),
        description="Container paths where most leaf data lives (densest first).",
    )
    sample_paths: tuple[str, ...] = Field(
        default=(),
        description="A few representative leaf paths from the sample.",
    )
    summary: str = Field(
        default="",
        description="Human/agent-readable digest for prompt injection.",
    )

    def context_block(
        self,
        *,
        name: str | None = None,
        volatility: str = "stable",
    ) -> ContextBlock:
        """Wrap `summary` as a ContextBlock for the personalized compile.

        Phase E injects this into the agent's prompt (via PromptAssembler)
        so the agent knows the client's datasource layout up front. The
        block defaults to 'stable' volatility — the structure changes
        rarely relative to per-turn data, so it sits early in the prompt
        and stays prefill-cache-friendly.
        """
        block_name = name or f"datasource:{self.datasource_name}"
        return ContextBlock(
            name=block_name,
            volatility=volatility,  # type: ignore[arg-type]
            content=self.summary,
            description=(
                f"Auto-profiled layout of client datasource"
                f" {self.datasource_name!r} ({self.kind})."
            ),
        )


def _infer_file_types(leaves: tuple["DatasourceItem", ...]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for leaf in leaves:
        label = leaf.item_type.strip()
        if not label:
            if "." in leaf.name and not leaf.name.startswith("."):
                label = leaf.name.rsplit(".", 1)[1].lower()
            else:
                label = "unknown"
        counter[label] += 1
    return dict(counter.most_common())


def _infer_naming(
    leaves: tuple["DatasourceItem", ...],
) -> tuple[str, dict[str, int]]:
    counter: Counter[str] = Counter()
    for leaf in leaves:
        counter[_classify_name(leaf.name)] += 1
    if not counter:
        return "unknown", {}
    distribution = dict(counter.most_common())
    top, top_n = counter.most_common(1)[0]
    total = sum(counter.values())
    # Dominant only if it covers a majority; else "mixed".
    convention = top if top_n * 2 > total else "mixed"
    return convention, distribution


def _infer_relevant_locations(
    leaves: tuple["DatasourceItem", ...], limit: int = 3
) -> tuple[str, ...]:
    counter: Counter[str] = Counter()
    for leaf in leaves:
        counter[_parent(leaf.path)] += 1
    return tuple(p for p, _ in counter.most_common(limit))


def _build_summary(
    *,
    name: str,
    kind: str,
    structure: "DatasourceStructure",
    top_level: tuple[str, ...],
    file_types: dict[str, int],
    naming: str,
    relevant: tuple[str, ...],
    max_depth: int,
    sample_paths: tuple[str, ...],
) -> str:
    containers = structure.containers()
    leaves = structure.leaves()
    lines: list[str] = []
    lines.append(
        f"Client datasource {name!r} (kind={kind}) rooted at"
        f" {structure.root!r}:"
    )
    lines.append(
        f"- Structure: {len(containers)} folders / {len(leaves)} files,"
        f" max depth {max_depth}"
        + (" (enumeration truncated)" if structure.truncated else "")
        + "."
    )
    if top_level:
        lines.append("- Top-level groups: " + ", ".join(top_level) + ".")
    if file_types:
        ft = ", ".join(f"{k} ({v})" for k, v in list(file_types.items())[:6])
        lines.append("- File types: " + ft + ".")
    if naming not in ("unknown", "mixed"):
        lines.append(f"- Naming convention: {naming}.")
    elif naming == "mixed":
        lines.append("- Naming convention: mixed (no single dominant style).")
    if relevant:
        lines.append(
            "- Most data lives under: " + ", ".join(relevant) + "."
        )
    if sample_paths:
        lines.append("- Example items: " + ", ".join(sample_paths[:5]) + ".")
    lines.append(
        "When the task needs this client's data, prefer the locations above"
        " and use the datasource's search / read-by-path tools."
    )
    return "\n".join(lines)


def profile_datasource(
    adapter: "DatasourceAdapter",
    *,
    sample_n: int = 5,
) -> DatasourceProfile:
    """Profile a connected datasource into a `DatasourceProfile`.

    Drives `connect -> enumerate_structure -> sample`, then infers layout,
    file-type distribution, naming convention, and likely-relevant
    locations, and renders a prompt-ready `summary`. Pure/deterministic
    over the adapter's (mockable) outputs.
    """
    adapter.connect()
    structure = adapter.enumerate_structure()
    sample = adapter.sample(sample_n)

    leaves = structure.leaves()
    containers = structure.containers()

    root = structure.root
    top_level_set: dict[str, None] = {}
    for item in structure.items:
        if item.is_container:
            tl = _top_level(item.path, root)
            if tl is not None and _depth(item.path, root) == 1:
                top_level_set.setdefault(tl, None)
    top_level = tuple(top_level_set)

    file_types = _infer_file_types(leaves)
    naming, naming_dist = _infer_naming(leaves)
    relevant = _infer_relevant_locations(leaves)
    max_depth = max(
        (_depth(i.path, root) for i in structure.items),
        default=0,
    )
    sample_paths = tuple(i.path for i in sample)

    summary = _build_summary(
        name=adapter.name,
        kind=adapter.kind,
        structure=structure,
        top_level=top_level,
        file_types=file_types,
        naming=naming,
        relevant=relevant,
        max_depth=max_depth,
        sample_paths=sample_paths,
    )

    return DatasourceProfile(
        datasource_name=adapter.name,
        kind=adapter.kind,
        root=root,
        container_count=len(containers),
        leaf_count=len(leaves),
        max_depth=max_depth,
        truncated=structure.truncated,
        top_level_groups=top_level,
        file_types=file_types,
        naming_convention=naming,
        naming_distribution=naming_dist,
        relevant_locations=relevant,
        sample_paths=sample_paths,
        summary=summary,
    )
