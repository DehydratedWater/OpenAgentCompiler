"""Generic definition-field mutators — tune arbitrary policy knobs.

The prompt/tool mutators assume an agent-shaped definition. Autoresearch
loops over arbitrary callables (`open_agent_compiler.improvement.autoresearch`) instead
carry plain parameter dicts — a checker's cooldown matrix, a ranking
function's weights, a workflow's retry budget. These mutators step such
knobs directly:

- :class:`NumericFieldMutator` — scale or shift a numeric field at a
  dotted path, with optional clamping. One instance per direction; give
  the loop a pair (e.g. ×1.5 and ×0.66) to let it hill-climb both ways.
- :class:`ChoiceFieldMutator` — rotate a field through an explicit set of
  allowed values (strategy names, modes, orderings).

Paths are dotted; integer segments index into lists ("tiers.0.cooldown").
A mutator returns None when the path is missing, the value isn't usable,
or the step produces no change — the loop just skips it.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from open_agent_compiler.improvement.mutators.base import MutationContext, Mutator
from open_agent_compiler.improvement.version import ComponentVersion


def _resolve(container: Any, segments: list[str]) -> tuple[Any, str | int] | None:
    """Walk to the parent of the addressed field. None when unreachable."""
    cursor = container
    for seg in segments[:-1]:
        if isinstance(cursor, list):
            if not seg.isdigit() or int(seg) >= len(cursor):
                return None
            cursor = cursor[int(seg)]
        elif isinstance(cursor, dict):
            if seg not in cursor:
                return None
            cursor = cursor[seg]
        else:
            return None
    last = segments[-1]
    if isinstance(cursor, list):
        if not last.isdigit() or int(last) >= len(cursor):
            return None
        return cursor, int(last)
    if isinstance(cursor, dict) and last in cursor:
        return cursor, last
    return None


class NumericFieldMutator(Mutator):
    """Scale (×) or shift (+) one numeric field, clamped to [minimum, maximum]."""

    name = "numeric_field"

    def __init__(
        self,
        path: str,
        *,
        scale: float | None = None,
        delta: float | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        name: str | None = None,
    ) -> None:
        if (scale is None) == (delta is None):
            raise ValueError("give exactly one of scale= or delta=")
        self.path = path
        self.scale = scale
        self.delta = delta
        self.minimum = minimum
        self.maximum = maximum
        step = f"*{scale}" if scale is not None else f"+{delta}"
        super().__init__(name or f"num:{path}{step}")

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        definition = json.loads(json.dumps(version.definition))
        target = _resolve(definition, self.path.split("."))
        if target is None:
            return None
        parent, key = target
        value = parent[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        new = value * self.scale if self.scale is not None else value + self.delta
        if self.minimum is not None:
            new = max(self.minimum, new)
        if self.maximum is not None:
            new = min(self.maximum, new)
        if isinstance(value, int) and isinstance(new, float) and new.is_integer():
            new = int(new)
        if new == value:
            return None
        parent[key] = new
        return ComponentVersion.of(
            version.component_id,
            version.kind,
            definition,
            parent_hash=version.content_hash,
            author=self.name,
        )


class ChoiceFieldMutator(Mutator):
    """Rotate one field through an explicit list of allowed values."""

    name = "choice_field"

    def __init__(
        self,
        path: str,
        choices: Sequence[Any],
        *,
        name: str | None = None,
    ) -> None:
        if len(choices) < 2:
            raise ValueError("choices needs at least two values to rotate")
        self.path = path
        self.choices = list(choices)
        super().__init__(name or f"choice:{path}")

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        definition = json.loads(json.dumps(version.definition))
        target = _resolve(definition, self.path.split("."))
        if target is None:
            return None
        parent, key = target
        value = parent[key]
        if value in self.choices:
            new = self.choices[(self.choices.index(value) + 1) % len(self.choices)]
        else:
            new = self.choices[0]
        if new == value:
            return None
        parent[key] = new
        return ComponentVersion.of(
            version.component_id,
            version.kind,
            definition,
            parent_hash=version.content_hash,
            author=self.name,
        )
