"""Per-client personalization — chat→spec elicitation + spec-seeded loop inputs.

Phase D of the per-client SaaS platform. A client describes their workflow in a
chat; this package turns that into a structured, validated `ClientSpec` and uses
the spec to SEED the autoloop's two graded signals:

  * `ClientSpec.example_tasks`   → the loop's PROBES (the client's own concrete
    tasks become the graded probes, via the Phase-0 `ProbeCache`/`ProbeSynthesizer`).
  * `ClientSpec.success_criteria` → the JUDGE rubric / `OptimisationCriterion`
    (candidates are scored on what the CLIENT said good means).

The only IO seam is the elicitation teacher call, which routes through opencode
(`OpencodeMutatorClient`) — never a raw provider API — and is mocked in tests.

Phase E (`PersonalizationRun`) consumes a `ClientSpec` + these seeded probes/judge
to run the per-client loop.
"""

from __future__ import annotations

from open_agent_compiler.personalization.elicit import (
    SpecElicitationError,
    TeacherClient,
    elicit_client_spec,
    parse_client_spec,
)
from open_agent_compiler.personalization.judge import (
    JUDGE_EVALUATOR_KIND,
    build_client_criterion,
    build_client_judge_test,
    build_client_rubric,
)
from open_agent_compiler.personalization.probes import (
    PROBE_KEY_PREFIX,
    example_task_probe_key,
    make_spec_probe_synthesizer,
    render_probe_text,
    seed_probes_from_spec,
    spec_probe_keys,
)
from open_agent_compiler.personalization.compile import (
    ClientOverlay,
    PersonalizedCompile,
    build_client_prompt_block,
    build_personalized_opencode_json,
    compile_personalized,
    overlay_variant,
    write_personalized_opencode_json,
)
from open_agent_compiler.personalization.run import (
    PersonalizationRun,
    PersonalizationRunResult,
    build_joint_mutators,
    build_session_judge_evaluator,
)
from open_agent_compiler.personalization.spec import ClientSpec, ExampleTask

__all__ = [
    # spec
    "ClientSpec",
    "ExampleTask",
    # elicitation (chat -> spec)
    "TeacherClient",
    "SpecElicitationError",
    "elicit_client_spec",
    "parse_client_spec",
    # spec-seeded probes
    "PROBE_KEY_PREFIX",
    "example_task_probe_key",
    "spec_probe_keys",
    "render_probe_text",
    "make_spec_probe_synthesizer",
    "seed_probes_from_spec",
    # spec-seeded judge
    "JUDGE_EVALUATOR_KIND",
    "build_client_rubric",
    "build_client_criterion",
    "build_client_judge_test",
    # per-client overlay compile (Phase E deliverable 1)
    "ClientOverlay",
    "PersonalizedCompile",
    "build_client_prompt_block",
    "overlay_variant",
    "build_personalized_opencode_json",
    "write_personalized_opencode_json",
    "compile_personalized",
    # per-client autoloop orchestrator (Phase E keystone)
    "PersonalizationRun",
    "PersonalizationRunResult",
    "build_joint_mutators",
    "build_session_judge_evaluator",
]
