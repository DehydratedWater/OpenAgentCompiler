"""TeacherGapRewriter — adapt prompts by studying a stronger model's gaps.

An autoloop can only find what its mutators can propose; behaviors the
loop "never discovered by itself" stay undiscovered. This mutator adds
an outside teacher: run the SAME harness with a stronger model on
example sessions (see `open_agent_compiler.evolve.reference`), capture
where the student's output diverges most, and ask the LLM to rewrite
the prompt specifically to close THAT gap — the teacher's excerpt shows
what better looks like, the student's shows what the current prompt
produces.

Wiring (the gap flows evaluator → sink → mutator between rounds):

    gaps: dict = {}
    evaluator = build_reference_evaluator(..., gap_sink=gaps)
    loop = IterativeLoop(
        ...,
        mutators=[IdentityMutator(), TeacherGapRewriter(gap_source=gaps)],
        evaluator=evaluator,
        mutation_context=MutationContext(llm=my_llm),
    )

Round N's evaluations fill the sink; round N+1's mutations read it.
On the first round (empty sink) the mutator no-ops — identity and the
other mutators seed the frontier, then the teacher signal kicks in.
"""

from __future__ import annotations

from typing import Any, Callable

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion

GapSource = Callable[[], dict[str, Any]] | dict[str, Any]

_GUIDANCE = (
    "A stronger reference model ran the SAME task with the SAME harness."
    " context.teacher_excerpt is its output; context.student_excerpt is"
    " what the current prompt produced; context.task is the task."
    " Rewrite the system prompt so the agent's behavior moves toward the"
    " teacher's — extract the GENERAL capability or habit the teacher"
    " displayed (structure, thoroughness, verification, idiom use), do"
    " not hardcode this one task's answer. Keep the persona; change only"
    " what closes the gap."
)


class TeacherGapRewriter(Mutator):
    """LLM prompt rewrite driven by the worst teacher/student divergence.

    Skips (returns None) when: no llm on the context, the version is not
    an agent, there's no system_prompt, or the gap source is empty /
    already closed (score above `skip_above`).
    """

    name = "teacher-gap-rewriter"

    def __init__(
        self,
        gap_source: GapSource,
        *,
        skip_above: float = 0.95,
        model: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.gap_source = gap_source
        self.skip_above = skip_above
        self.model = model

    def _gap(self) -> dict[str, Any]:
        if callable(self.gap_source):
            return dict(self.gap_source() or {})
        return dict(self.gap_source)

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent" or ctx.llm is None:
            return None
        defn = dict(version.definition)
        current = defn.get("system_prompt", "")
        if not current:
            return None
        gap = self._gap()
        if not gap.get("teacher_excerpt"):
            return None
        if float(gap.get("score", 0.0)) >= self.skip_above:
            return None
        try:
            rewritten = ctx.llm.rewrite(
                target=current,
                guidance=_GUIDANCE,
                context={
                    "task": gap.get("prompt", ""),
                    "task_id": gap.get("task_id", ""),
                    "gap_score": gap.get("score", 0.0),
                    "teacher_excerpt": gap.get("teacher_excerpt", ""),
                    "student_excerpt": gap.get("student_excerpt", ""),
                },
                model=self.model,
            )
        except Exception:  # a flaky rewriter must not sink the round
            return None
        if not rewritten or rewritten.strip() == current.strip():
            return None
        defn["system_prompt"] = rewritten
        return ComponentVersion.of(
            component_id=version.component_id,
            kind=version.kind,
            definition=defn,
            parent_hash=version.content_hash,
            author=self.name,
        )
