# Optimize the real goal, not "text correctness" — context matters

A field lesson from a production improvement loop. The loop made agents that
scored *great* in the loop and delivered **nothing** in production. The cause was
not the model, the teacher, or the search — it was **what we measured**.

> You get what you measure. Optimise a proxy that diverges from the real goal,
> with nothing exercising the real path until live use, and the loop will happily
> perfect the proxy while the real goal silently rots.

## The story (symptom → cause → fix)

**Symptom.** After tuning, a briefing agent produced a polished 1253-character
briefing in the loop and scored near the top. In production it sent **nothing** to
the user. Several "optimised" agents regressed the same way: loop scores up, real
delivery gone.

**Cause.** Production delivery for these agents does **not** happen through the
assistant's text. The user never sees the assistant prose. Delivery happens when
the agent calls a specific tool — `emit_guidance.py` — whose emitted payload is
what actually reaches the user. The autoloop, however, judged candidates on the
**assistant TEXT output**. That text was a *proxy* for the goal, and the proxy had
diverged from the real delivery contract. The teacher's rewrites optimised the
proxy: they polished the prose and, in doing so, **silently dropped the
load-bearing `emit_guidance` tool-call**. Because the loop only ever read the
text, nothing exercised the real delivery path until a live user hit it.

**Fix.** Optimise and evaluate against the system's **real goal in context**:

- The evaluator now **gates on the production contract** — did the agent call the
  required tool / emit the required artifact / satisfy the downstream contract.
  A run that does not is scored **0**, regardless of how good its text is.
- The judge grades the **delivered payload** (what `emit_guidance` emitted), not
  the assistant prose.
- The teacher/rewriter is **told never to drop load-bearing contracts**.
- Probes and the judge rubric reflect the **real goal and its context** (the
  agent's job is to *deliver via the tool*, not to *write a nice answer*).

## The principle

**Optimise/evaluate against the system's real goal in context — the production
contract / outcome / side-effect — not the "pure correctness" of the text
output.** A beautiful-but-undelivered answer is a **failure**, and the loop must
score it as one. Concretely:

1. **The evaluator must check the production contract.** Did the required
   side-effect happen? Required tool called? Deliverable emitted? Downstream
   contract satisfied? If not → **score 0** and record *why*. Never let a candidate
   win on text while the load-bearing action is missing.
2. **Grade the real deliverable, not the assistant text.** Judge the emitted
   payload / artifact / side-effect — the thing the user/system actually receives.
   The assistant prose may be invisible; do not optimise it as if it were the
   product.
3. **The teacher/rewriter must preserve load-bearing contracts.** Tell it
   explicitly: keep the required tool-call / delivery step / output format; you may
   rewrite *how* the agent works, never *whether* it delivers.
4. **Probes + judge rubric must reflect the real goal and its context.** Write
   probes that exercise the real path (the agent has to deliver to pass) and a
   rubric scoped to the real outcome, so the loop's signal *is* the production
   signal.

## How (the framework primitive)

The framework ships a reusable gate so an evaluator enforces this by construction:
`open_agent_compiler/improvement/contract_gate.py` (exported from `open_agent_compiler.improvement`).

```python
from open_agent_compiler.improvement import contract_gate, require_tool_called, RunOutcome
from open_agent_compiler.improvement import build_session_judge_evaluator   # per-client path

base = build_session_judge_evaluator(...)        # judges the DELIVERED payload quality

gated = contract_gate(
    base,
    contract=require_tool_called("emit_guidance"),     # the production contract
    outcome_for=lambda version: capture_run(version),  # -> RunOutcome over the trajectory
)
```

`contract_gate(base, contract=..., outcome_for=...)`:

- runs the base evaluator (so the judge **still grades the quality of the
  delivered payload**), then checks `contract` against the candidate's run;
- when the contract is **not** satisfied, forces every score-shaped metric
  (`score_floor`, `score_mean`, `pass_rate`, the per-client judge key) to **0.0**,
  sets `contract_satisfied=0.0` (so a **hard** `Criterion` can disqualify it), and
  appends the failure reason to a `failures_sink` so the teacher's next rewrite is
  told it dropped a load-bearing contract;
- composes with everything else: the loop keeps ranking on the same metrics, but a
  candidate only earns a non-zero score once it actually delivers.

`RunOutcome` is a framework-native view over one run that reuses the existing
trajectory structures — `ToolCallRecord` (`RunContext.tool_calls` /
`BranchTrajectory.tool_calls`), the `subagent_dispatch_chain` parse helper, and an
`artifacts` map for emitted deliverables. Ready-made predicates:

| Predicate | Contract it enforces |
|---|---|
| `require_tool_called("emit_guidance")` | the delivery tool fired (substring match) |
| `require_any_tool_called([...])` | at least one of several delivery paths fired |
| `require_artifact("briefing", predicate=...)` | a named deliverable was emitted (and optionally passes a content check) |
| `require_subagent_dispatched("delivery")` | an orchestrator routed to the agent that actually delivers |
| `all_of(p1, p2, ...)` | every contract holds (conjunction) |

`require_outcome(...)` is a readability alias for `contract_gate(...)`. Write your
own `ContractPredicate` (`RunOutcome -> ContractResult`) for any bespoke contract.

## Per-client / SaaS-moat implication

This is **doubly critical** for the per-client/SaaS platform (the moat). Per-client
optimisation must optimise against **each client's real workflow contract**, not a
text stand-in. Each client's deliverable is different — one emits a guidance
payload, another writes to a Drive doc, another posts to an MCP endpoint, another
returns structured JSON a downstream system consumes. If the per-client autoloop
grades assistant prose, it will perfect prose and silently break the client's
actual workflow. The per-client evaluator (`build_session_judge_evaluator`) should
be wrapped in `contract_gate` with that client's delivery contract, and the
probes/rubric seeded from `ClientSpec.success_criteria` must describe the real
delivery — so "auto-optimised for this client" means "actually delivers this
client's outcome." See `docs/plans/per-client-personalized-saas-platform.md`
(Phase E).

## What's now tested

`tests/improvement/test_contract_gate.py` locks the principle (pure/mocked — no
live opencode/qwen/z.ai):

- a contract-honoring candidate (calls `emit_guidance`) scores **high**, while an
  otherwise text-identical candidate that never delivers scores **0**;
- the gate **composes** with the judge — two delivering candidates are still ranked
  by their delivered-payload quality;
- a **regression** test: under a naive text-judge the slightly-prettier-but-
  undelivered candidate *wins* (the production disaster); under `contract_gate` the
  delivering candidate wins instead;
- the gate's `contract_satisfied` metric drives a **hard** criterion so an
  undelivered candidate is disqualified outright.

## See also

- `docs/lessons/tuning-a-local-agent-fleet.md` — the 6/137 → 109/137 field report;
  this lesson is the next one after the flailing/discovery fixes.
- `docs/lessons/thinking-models-and-opencode-scoring.md` — score agents as full
  opencode sessions, not bare `/chat/completions` calls (same family of mistake:
  measuring the wrong thing).
- The `improvement-loop` skill — operational recipe + this lesson's summary.
