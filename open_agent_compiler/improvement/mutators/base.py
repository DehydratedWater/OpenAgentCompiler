"""Mutator base + MutationContext."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.version import ComponentRegistry, ComponentVersion


class MutationContext(BaseModel):
    """Everything a mutator might need to make an informed change.

    Fields are intentionally narrow — the loop populates only what it
    has; mutators handle missing pieces gracefully.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry: ComponentRegistry | None = None
    criterion: OptimisationCriterion | None = None
    # Per-failure evidence pulled from the JSONL artifacts so the
    # mutator can target what actually regressed.
    failures: list[dict[str, Any]] = Field(default_factory=list)
    # Optional LLM client for LLM-backed mutators (typed Any so
    # Pydantic accepts any duck-typed impl).
    llm: Any = None
    extras: dict[str, Any] = Field(default_factory=dict)


class Mutator(ABC):
    """Subclass to produce candidate ComponentVersions.

    `name` becomes the `author` field on emitted versions so lineage
    queries show which mutator produced which candidate.
    """

    name: str

    def __init__(self, name: str | None = None) -> None:
        # Allow per-instance override for tests; default to class attr.
        if name is not None:
            self.name = name

    @abstractmethod
    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        """Return a candidate, or None if this mutator doesn't apply.

        Implementations should:
        1. Decide if `version` is mutable by this mutator (else return None).
        2. Compute the new definition dict.
        3. Use ComponentVersion.of(..., parent_hash=version.content_hash,
           author=self.name) so lineage is preserved.
        """
