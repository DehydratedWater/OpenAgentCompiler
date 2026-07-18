"""ClientSpec — a client's workflow distilled into a structured, validated spec.

The per-client SaaS platform starts from a free-form CHAT in which the client
describes what they want the agent to do. Phase D turns that chat into a
`ClientSpec`: a frozen Pydantic record with the goal, preferences, constraints,
concrete example tasks, and the client's own definition of "good". That spec is
the single source of truth the rest of the pipeline reads from:

  * `ClientSpec.example_tasks`   → seed the autoloop's PROBES (the graded tasks
    the loop climbs — see `seed_probes_from_spec` in `probes.py`).
  * `ClientSpec.success_criteria` → seed the JUDGE rubric / `OptimisationCriterion`
    so candidates are scored on what the CLIENT said good means (see `judge.py`).

This module is pure data + validation — no IO. The chat→spec extraction (the
single teacher/IO seam) lives in `elicit.py` and is always mocked in tests.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class ExampleTask(BaseModel):
    """One concrete task the client expects the agent to handle.

    `prompt` is a real input/instruction the agent would receive (it becomes a
    probe verbatim). `expected_outcome` is an optional free-text note on what a
    good result looks like for THIS task — woven into the probe/judge context as
    a soft hint, never a hard string match.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str
    expected_outcome: str = ""

    @model_validator(mode="after")
    def _prompt_non_empty(self) -> "ExampleTask":
        if not self.prompt.strip():
            raise ValueError("ExampleTask.prompt must be non-empty")
        return self


class ClientSpec(BaseModel):
    """A client's workflow as a structured, validated spec (frozen).

    Fields:
    - goal: one-sentence statement of what the client wants the agent to do.
    - preferences: soft 'how they like it done' guidance (tone, defaults, …).
    - constraints: hard rules the agent must respect (never do X, always Y).
    - example_tasks: concrete tasks → become the autoloop probes. At least one
      is required for a spec to be USABLE (see `is_usable` / `require_usable`).
    - success_criteria: the client's own statements of what "good" means →
      become the judge rubric / OptimisationCriterion.

    Validation: `goal` must be non-empty. A spec with no `example_tasks` is
    permitted to EXIST (an early/partial elicitation) but is not USABLE for
    seeding a loop; `require_usable()` enforces the stronger contract at the
    point a loop is about to consume it.
    """

    model_config = ConfigDict(frozen=True)

    goal: str
    preferences: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    example_tasks: tuple[ExampleTask, ...] = ()
    success_criteria: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _goal_non_empty(self) -> "ClientSpec":
        if not self.goal.strip():
            raise ValueError("ClientSpec.goal must be non-empty")
        return self

    @property
    def is_usable(self) -> bool:
        """True when the spec carries ≥1 example task (can seed a loop)."""
        return bool(self.example_tasks)

    def require_usable(self) -> "ClientSpec":
        """Return self if usable; else raise — call before seeding a loop.

        A usable spec must have at least one example_task (so probes can be
        synthesised) and at least one success_criterion (so the judge rubric is
        grounded in the client's definition of good).
        """
        if not self.example_tasks:
            raise ValueError(
                "ClientSpec is not usable: it has no example_tasks to seed probes"
            )
        if not self.success_criteria:
            raise ValueError(
                "ClientSpec is not usable: it has no success_criteria to seed the"
                " judge rubric"
            )
        return self


__all__ = [
    "ExampleTask",
    "ClientSpec",
]
