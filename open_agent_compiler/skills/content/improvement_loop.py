"""improvement-loop skill — the iterative-improvement workflow."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Improvement loop — autoresearch for agents, tools, and skills

The framework turns the same compile/test pipeline back on the
project's own definitions: candidate prompts (or tool descriptions,
or sampling configs, or skills) are generated, evaluated, scored,
and the winners are promoted back into the source so the next
compile ships the improved version. Run this as often as you like;
each cycle is bounded by `--max-iters`.

## CLI

```bash
# Run a loop against one component
uv run oac improve agents:registry \\
    --target my-orchestrator \\
    --criteria criteria.yaml \\
    --max-iters 5

# Per-model class loops — one optimised winner per class
uv run oac improve agents:registry \\
    --target my-orchestrator \\
    --criteria criteria.yaml \\
    --split-profile per-model

# Promote the winning snapshot back into the project
uv run oac promote improved/my-orchestrator/<hash>.json
# Per-class promotion (writes .oac/promoted/<id>__<class>.json)
uv run oac promote improved/my-orchestrator/<hash>.json --class fast

# Next compile picks up the promoted version transparently — your
# registry uses `register_with_improvements` so the merge is automatic.
uv run python build_agents.py
```

## What each cycle does

1. Read the latest JSONL test artifacts under `.oac/test_results.jsonl`
   for the target component.
2. Build a `MutationContext` from the failing/low-score evidence.
3. For each registered Mutator (prompt prefix/suffix, temperature,
   tool-description, tool-format, LLM rewriter, or your custom one),
   produce a candidate `ComponentVersion`.
4. Compile + test each candidate against the same MockProfile +
   AccessProfile + criteria the baseline ran under.
5. Score each candidate against the `OptimisationCriterion`. The
   winner gets snapshotted under
   `improved/<component>/<short_hash>.json`.

## Writing a criterion

```yaml
# criteria.yaml
name: full-explanations
aggregation: weighted
criteria:
  - kind: pass_rate
    target: 1.0
    weight: 2.0
  - kind: score_floor
    scope: by_name
    scope_value: response-mentions-tradeoffs
    target: 1.0
    weight: 1.0
  - kind: tool_failure_rate
    target: 0.05         # ≤5% tool calls may error
    weight: 1.0
```

Use `Criterion.for_named(name, kind, target)` in Python for the
common case where you want one criterion per named evaluator.

## Mutators you can register

| Mutator | Targets | What it does |
|---|---|---|
| `IdentityMutator` | any | Control candidate (returns unchanged). |
| `PromptPrefixMutator(prefix)` | agent | Prepend a string to `system_prompt`. |
| `PromptSuffixMutator(suffix)` | agent | Append a string to `system_prompt`. |
| `TemperatureMutator(delta)` | agent | Nudge sampling temperature within bounds. |
| `LLMPromptRewriter(client)` | agent | Use a model to rewrite the prompt given failures. |
| `ToolDescriptionAppendMutator(suffix)` | tool | Append a clarifier to `tool.header.description`. |
| `ToolRuleAddMutator(rule)` | tool | Append a rule entry to `tool.rules`. |
| `ToolFormatMutator("bash"|"json"|"both")` | agent | Vary `default_tool_format` to see which form a model performs best with. |
| `ImprovementAgentMutator(invoker)` | agent | Delegate to a framework-compiled improvement agent that reads the JSONL and proposes one minimal patch. |

Mix and match in a `mutators=[...]` list when you build the
`IterativeLoop`. The order matters: the loop tries each mutator
once per round and keeps Pareto-frontier candidates.

## Per-class optimisation

When the project compiles via a `SplitProfile` (one model class per
preset — fast / analytical / local), use `run_per_class_loops` so the
loop optimises *independently per class*. The output lands under
`improved/<component>/<class>/<hash>.json`. Promote with
`--class <name>` and the resolver picks the per-class slot first,
falling back to the default slot when no class-specific promotion
exists.

## Closing the loop — `register_with_improvements`

```python
agent_id = reg.register_with_improvements(
    "my-orchestrator", baseline,
    ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    project_root=PROJECT_ROOT,
    model_class="fast",        # picks the class-specific slot when present
)
```

The walk handles the whole composable tree: the agent itself, each
skill, each tool reachable through any skill's workflow steps, and
every `extra_tools` entry. Pieces without a promoted snapshot pass
through at baseline; pieces with one merge in automatically.

## When to run improvement vs leave the baseline alone

- Run when you have ≥5 embedded tests covering the behaviour you
  care about and at least one of them is failing or low-scoring.
- Don't run on prompts under 20 words — the mutator search space is
  too small to find a meaningfully different winner.
- Don't run with one criterion at `target=1.0`; you'll get
  no signal once the first candidate passes. Stack 2-4 criteria
  with mixed weights to keep the loop discriminative.

## Real-evaluation primitives (Phases 30 + 36)

The Identity / PromptPrefix / TemperatureMutator candidates score
trivially against keyword-counting rubrics. Real evaluation needs
to invoke each candidate as an opencode subprocess against a held-
out eval set and judge the output. Three framework primitives
together make this a ~30 LOC evaluator:

```python
from open_agent_compiler.improvement import (
    OpencodeRunner, write_test_variant_md, build_parent_mimic_prompt,
)

runner = OpencodeRunner(build_dir=Path("build"))

def evaluator(version):
    # 1. Compile the candidate as a primary-mode .md.
    agent_name, path = write_test_variant_md(
        version.definition,                       # accepts dict or AgentDef
        build_dir=Path("build"),
        model="zai-coding-plan/glm-4.5-air",
        name_prefix="my_eval",
    )
    try:
        errors = []
        for case in EVAL_SET:
            # 2. Build a user message in the shape a parent would send.
            prompt = build_parent_mimic_prompt(
                target_agent_name="judge",
                target_description="Score adherence 0-1.",
                eval_case=case,
                parent_description="my-orchestrator",
            )
            # 3. Run opencode (sync; auto-retries on empty output;
            #    auto-clamps off-scale scores).
            result = runner.run(
                agent_name=agent_name, prompt=prompt, timeout_s=120,
            )
            score = result.score_field("score")  # → 0..1 or None
            errors.append(
                1.0 if score is None else abs(score - case["expected"])
            )
    finally:
        path.unlink()  # don't pollute build/.opencode/agents/
    mae = sum(errors) / len(errors)
    return {"mae": mae, "score_floor": max(0.0, 1.0 - mae)}
```

`OpencodeRunner` (Phase 36) is the recommended sync invoker. It:
  - Sets `XDG_DATA_HOME` + `PWD` automatically.
  - Auto-retries once when first attempt returns rc=0 + zero text
    events (transient opencode failure mode).
  - `result.score_field(name)` clamps to (0, 1) by default — agents
    that drift the output scale (e.g., return 8 on a 0-1 rubric)
    get None instead of polluting the MAE math.
  - `result.json_objects(must_contain_key=...)` for richer outputs.

`write_test_variant_md` emits an isolated primary-mode .md so a
subagent (which can't be invoked directly via `opencode run`) can
be evaluated standalone. Deletes itself on `path.unlink()`.

`build_parent_mimic_prompt` constructs the user message in the
shape the real orchestrator would have sent — important because
ad-hoc raw prompts don't exercise the same prompt-handling code
path as production invocations.

For `LLMPromptRewriter` to actually fire and produce a candidate
that beats the baseline, start the loop from a deliberately-weak
baseline — `register_with_improvements`-merged prompts are
typically already near-optimal so the rewriter has nothing to
improve. The pattern proven in a production consumer is the
reference: overwrite the registered prompt with a stripped-down
version before passing to `IterativeLoop`.

## Closing the loop verified live

The framework's autoresearch produced a real positive delta against
a real eval set: weak baseline `score_floor=0.900` → best candidate
`score_floor=0.988` (+0.088). 12 real opencode invocations + 1
real glm-5.1 rewrite call. Winners written to `improved/`;
`oac promote` copied the chosen snapshot into `.oac/promoted/`;
`build_agents.py` merged the suffix into the compiled
`transcript-scorer.md` (the rebuilt file contained "Use scale 0-1,
NOT 0-10" exactly as the promoted prompt specified). The loop is
real; the plumbing is verified end-to-end.

## How to run the loop on a local model stack (operational recipe)

Hard-won from tuning a 137-agent fleet (GLM-5.1 teacher → Qwen-27B
student): the result went **6/137 → 63/137 promoted** once the run
was set up the way below. Every step here exists because skipping it
silently zeroed scores.

1. **Everything runs through opencode — student AND teacher.** The
   agent-under-test runs as a full `opencode run` session on its
   model (e.g. local `qwen35-27b`). The teacher/judge/probe-writer
   ALSO run as opencode agents (e.g. `zai-coding-plan/glm-5.1`),
   NEVER via a raw provider API. Direct `api.<provider>/chat/
   completions` calls can violate the provider's ToS and get the
   account banned — and they aren't a real test of the agent. Same
   opencode path for both; only the model differs.

2. **Run from the opencode PROJECT ROOT** (the dir holding
   `opencode.json`) so agents are discovered, and **install each
   candidate FLAT-named** into `<root>/.opencode/agents/cand_<hex>.md`
   (never nested/slashed — opencode won't resolve `a/b-primary`).

3. **Warm a dedicated opencode web server** on its own port and
   **warm up discovery** (run one throwaway flat candidate until it
   resolves) before grading, so the server's rescan lag doesn't 0 the
   first candidate.

4. **Sessions land in `<root>/.opencode/data`** (set `XDG_DATA_HOME`
   to it for both the server and the runs) so you can watch the loop
   live in the opencode UI pointed at the project.

5. **Pre-synthesise probes** (the per-agent test prompts the teacher
   writes) IN PARALLEL and cache them to disk before the run —
   otherwise 100+ sequential teacher calls stall the loop in setup
   for tens of minutes. Persist only real probes, never offline
   fallbacks.

6. **Surface opencode error events** in the runner (see the GOTCHA
   below) — the single most important safeguard.

7. **Model sampling:** use the model's recommended settings
   (e.g. Qwen3.x: temperature 1.0, top_p 0.95, top_k 20, thinking
   ON) with an adequate token budget. Confirm a plain probe returns
   non-empty text >95% of the time before trusting the run.

8. **Give the agent's TOOLS the runtime they expect, and watch for
   debug-flailing.** Tool/orchestrator agents run their tools as
   subprocesses — e.g. `python scripts/<tool>.py` — which the bash
   tool launches with the SYSTEM python unless you fix the env. If it
   hits the wrong interpreter (no deps) or a missing `PYTHONPATH`, the
   script dies on `ModuleNotFoundError` and the agent produces nothing
   → scores 0. Pass the loop's own deps-having interpreter first on
   `PATH` (+ `uv`, `opencode`) and propagate `PYTHONPATH` into the run.
   EDGE CASE: agents are compiled with an ALLOW-LIST of permitted
   commands (just their own `python scripts/*.py`). When a tool fails,
   a thinking model tends to *debug-flail* — `pip install …`,
   `which python`, `ls`, `python3 -c …` — all DENIED by the policy,
   retried repeatedly, the turn wasted, the score tanked. Two fixes:
   (a) make the real tools actually work (the env above), and (b) a
   prompt that tells the agent NOT to inspect/install/debug the
   environment — use its allowed tools or report failure. Unit tests
   can't see this; a live smoke can assert the count of
   permission-DENIED tool calls per run stays ~0 (the runner exposes a
   `blocked_tool_attempts(stdout)` detector for exactly this).

9. **Orchestrators need NON-single-shot grading.** An orchestrator's
   job is a multi-step session (it may spawn sub-agents); a one-turn
   judge under-scores it. Run it as a FULL multi-step opencode session
   (whole fleet compiled in so it can spawn sub-agents, runtime env
   wired) and judge the OUTCOME — did the final response fulfil the
   request — with the documented dispatch path as a SOFT hint, NOT a
   hard path-match (orchestrators often do the work themselves). When it
   acts only via tools with no prose, show the judge the trajectory (the
   spawned-agent chain). True dispatch-PATH verification needs the full
   production orchestration runtime (warm manager server + sandbox +
   exact permissions) — outcome-judging works today, path-verification
   is the remaining headroom.

10. **Optimise the REAL goal, not a TEXT PROXY.** Judge candidates on the
   production contract — the required side-effect — not "is the text good." In a
   real run the loop judged assistant TEXT, but delivery happened via a tool-call
   (`emit_guidance.py`) whose payload is what the user sees; the teacher's rewrites
   polished the prose and silently DROPPED the load-bearing tool-call, so optimised
   agents scored great and delivered NOTHING live. Fix: the evaluator GATES on the
   contract (required tool called / artifact emitted / side-effect happened) and
   scores 0 when it's absent; the judge grades the DELIVERED payload, not the
   prose; the teacher is told never to drop load-bearing contracts; probes + rubric
   reflect the real goal. Use `contract_gate` (next section). Full writeup:
   `docs/lessons/optimize-the-real-goal-not-text-correctness.md`.

The full field report — every problem that bit (mass-zero discovery,
ToS, env, flailing, single-shot limits) and the working process — is in
`docs/lessons/tuning-a-local-agent-fleet.md` (6/137 → 109/137).

## These hardening fixes are now IN CORE — import, don't re-implement

Every fix above ships in `open_agent_compiler.improvement` / `open_agent_compiler.testing`; a consumer
should import them rather than re-hand-rolling (the re-implementation gap
is exactly what made three consumers ship raw provider-API calls). The
canonical names:

- **Teacher via opencode** — `OpencodeMutatorClient` (a first-class
  `LLMMutatorClient` + `.judge(...)`). NEVER a raw provider call. Wire it
  into `LLMPromptRewriter` via `MutationContext(llm=OpencodeMutatorClient(...))`.
- **Error surfacing** — `OpencodeRunner` now sets `result.error` on a
  `{"type":"error"}` event (the mass-zero class) and retries it. Helpers:
  `opencode_errors`, `subagent_dispatch_chain`, `blocked_tool_attempts`.
- **Flat candidate from project root** — `find_project_root`,
  `flat_candidate_from_project_root`, `clear_candidates`, `warmup_discovery`.
- **Tool-discipline guard (opt-in)** — `apply_tool_discipline(defn)` /
  `tool_discipline_postamble()`.
- **Deps-env** — `deps_env(interpreter=..., pythonpath=..., propagate=...)`.
- **Probe cache** — `ProbeCache(path, synthesize=...)` (`.prewarm`, `.get`);
  fallbacks are never persisted.
- **Outcome-judged branch (the orchestrator DEFAULT)** —
  `build_outcome_branch_loop` / `build_outcome_branch_evaluator` /
  `make_branch_outcome_judge_test` (soft path hint, not a hard match). The
  path-match `build_branch_loop` stays for when the exact chain IS the contract.
- **Raw-provider AST guard (SHIP IT)** —
  `from open_agent_compiler.testing import assert_no_raw_provider_endpoints`; call it over your
  repo root in your own test suite to fail the build if any raw
  `…/chat/completions` / `api.z.ai` endpoint appears in loop code.
- **Contract gate (optimise the REAL goal)** — `contract_gate(base_evaluator,
  contract=..., outcome_for=...)` (alias `require_outcome`). Wrap ANY evaluator so a
  candidate that did NOT satisfy the production contract over its run trajectory is
  forced to score 0 (and the reason recorded for the teacher). Ready predicates:
  `require_tool_called`, `require_any_tool_called`, `require_artifact`,
  `require_subagent_dispatched`, `all_of`; the run view is `RunOutcome` (reuses
  `ToolCallRecord` + `subagent_dispatch_chain`). The base evaluator still grades the
  DELIVERED payload's quality; the gate only zeroes undelivered candidates. This is
  the fix for "loop scores great, production delivers nothing." See
  `docs/lessons/optimize-the-real-goal-not-text-correctness.md`.

## GOTCHA — score agents ONLY as full opencode sessions in a
## DISCOVERABLE project, and surface opencode errors (the "mass-zero" trap)

An agent's score MUST come from running it the way it runs in
production: a **full `opencode` session, driven to auto-termination**,
in a **discoverable project context**, with its real tools and runtime.
Do NOT "shortcut" the score with a bare `/chat/completions` call — that
skips tools, the agentic loop, and the runtime, so it is not a test of
the agent and will mis-rank candidates.

The mass-zero trap (a real run promoted only **6 of 137**): the loop
compiled each candidate into an **ephemeral temp dir** with a **nested /
slashed** agent name, and opencode could not discover it —

```
{"type":"error","error":{"data":{"message":
  "Agent not found: \"persona/responding-primary\". Available agents: build, explore, general, plan"}}}
```

opencode reports this as an **error event while exiting 0**, and the
runner's parser returned `""` for it, so the judge scored the empty
string 0. A whole fleet of **agent-DISCOVERY** failures looked like the
model "returning nothing" — which is a trap that wastes hours chasing a
non-existent model/thinking bug.

What actually fixes it (mirror a warm `opencode_manager` setup):
- Run candidates from a **stable project dir** carrying `opencode.json`
  (so opencode treats it as a project) — NOT an ad-hoc temp dir.
- Install candidates **FLAT-named** (`cand_<hex>.md`), never nested /
  slashed (`a/b-primary`), which opencode does not resolve.
- Keep a **warm dedicated opencode server** and **warm up discovery**
  (run a throwaway flat candidate until it resolves) so the server's
  rescan lag does not 0 the first candidate of a run.
- **Surface opencode `{"type":"error"}` events** in the runner →
  `result.error`, NEVER empty text. This one safeguard catches the whole
  class of failure immediately.

Secondary (do not be misled): Qwen3.x is a thinking model and *can*
return empty if starved of tokens; `chat_template_kwargs.enable_thinking
=false` (request body) is the only per-call disable and **opencode drops
it**. But with reliable discovery + adequate budget + a warm server,
thinking-on is reliable. Do NOT disable thinking to "fix" empties before
confirming they are not swallowed opencode errors.

Checklist before trusting an improvement run on a local model:
1. Run a plain agent probe ~10× from the SAME context the loop uses. If
   any come back blank, print `result.error` — it is almost certainly
   `Agent not found` / a provider error, not the model.
2. Score only as full opencode sessions in a discoverable project
   (stable dir + `opencode.json` + flat agent name + warm server).
3. Never let an opencode error event pass as empty assistant text.
4. Use concrete, fully self-contained probes (input data inline); never
   "demonstrate your core function" prompts.

See also: `writing-tests`, `variants-and-profiles`,
`authoring-agents` (`register_with_improvements` + `also_compile_as_primary`).
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="improvement-loop",
        description=(
            "The iterative-improvement workflow: oac improve / oac"
            " promote / register_with_improvements. Mutators, criteria,"
            " per-class optimisation, and how to wire it all back into"
            " the project."
        ),
        body_markdown=BODY,
        version="1.0.0",
        tools_hint=(
            "oac improve", "oac promote", "criteria.yaml",
            "register_with_improvements", "apply_promoted_to_tree",
        ),
    )
