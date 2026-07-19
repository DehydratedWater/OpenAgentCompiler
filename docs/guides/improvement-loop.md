# The improvement loop

In this guide you'll run closed-loop optimization on an agent: define
what "better" means as an `OptimisationCriterion`, let mutators generate
candidate versions, evaluate them, snapshot the winners, and promote the
best one back into your registry so the next compile ships it.

Prerequisites: a registered agent with [embedded tests](testing.md) or
an evaluator of your own. The loop is: mutate → compile → evaluate →
keep the Pareto frontier → snapshot.

## 1. Define the criterion (criteria YAML)

An `OptimisationCriterion` bundles one or more `Criterion` entries with
an aggregation rule (`all` = every soft criterion must pass; `weighted`
= weight-normalized continuous score). Criterion kinds: `pass_rate`,
`score_floor`, `score_mean`, `score_quantile`, `latency_p95`,
`cost_ceiling`, `determinism`, `tool_failure_rate`.

```yaml
# criteria.yaml
name: full-explanations
aggregation: weighted
criteria:
  - kind: pass_rate
    target: 1.0
    weight: 2.0
  - name: response-mentions-tradeoffs
    kind: score_floor
    scope: by_name
    scope_value: response-mentions-tradeoffs
    target: 1.0
    weight: 1.0
  - kind: tool_failure_rate
    target: 0.05        # at most 5% of tool calls may error
    weight: 1.0
    hard: true          # must be met regardless of weighted score
```

In Python, `Criterion.for_named(name, kind, target)` is shorthand for a
`by_name`-scoped criterion whose name matches the metric key your
evaluator emits (e.g. `score_floor:by_name:response-mentions-tradeoffs`).
Don't run a single criterion at `target=1.0` — once one candidate
passes there's no signal left; stack 2-4 criteria with mixed weights.

## 2. Choose mutators

Bundled mutators from `open_agent_compiler.improvement.mutators`:

| Mutator | Targets | Effect |
|---|---|---|
| `IdentityMutator` | any | Control candidate — always include it |
| `PromptPrefixMutator(text)` / `PromptSuffixMutator(text)` | agent | Deterministic prompt nudges |
| `TemperatureMutator(delta)` | agent | Sampling nudge within bounds |
| `LLMPromptRewriter(guidance=...)` | agent | An LLM rewrites the prompt against your criteria and failure evidence |
| `SectionRewriterMutator` (via `make_section_mutators`) | agent | Rewrites one named `prompt_sections` entry in place — improve, never gut |
| `ToolDescriptionAppendMutator(suffix)` / `ToolRuleAddMutator(rule)` | tool | Tool-targeted doc/rule mutations |
| `ToolFormatMutator("bash"\|"json"\|"both")` | agent | Varies the tool contract format to see which the model handles best |
| `ImprovementAgentMutator(invoker)` | agent | Delegates to a compiled improvement agent that reads the JSONL and proposes one minimal patch |
| `WorkflowStepAppendMutator(step)` / `WorkflowStepRemoveMutator(name)` | agent | Structural: add or drop a workflow step — the loop can grow the process, not just the prose |
| `ToolAttachMutator(tool)` / `ToolDetachMutator(name)` | agent | Structural: grant or revoke a tool on the candidate |
| `LLMWorkflowEditor(...)` | agent | An LLM proposes one structural workflow edit (optionally fed teacher-gap evidence via `gap_source`) |
| `TeacherGapRewriter(...)` | agent | Rewrites the prompt from the gaps a stronger teacher model exposed (see [evolve guide](evolve-coding-harness.md)) |

LLM-backed mutators take a client via
`MutationContext(llm=...)`. Two clients ship:

- `OpencodeMutatorClient(model=...)` — routes the rewrite through an
  opencode session (no provider keys in your code).
- `OpenAICompatMutatorClient.from_env()` — talks to any
  OpenAI-compatible endpoint directly; reads `OAC_MUTATOR_MODEL`,
  `OAC_MUTATOR_BASE_URL`, `OAC_MUTATOR_API_KEY` (falling back to
  `LIVE_MODEL_ID` / `LIVE_BASE_URL` / `LIVE_API_KEY`) and returns
  `None` when unconfigured — so loops can degrade gracefully to
  deterministic mutators.

## 3. Run the loop

Via the CLI (bundled mutator names: `identity`, `prompt-prefix:<text>`,
`prompt-suffix:<text>`, `temperature:<delta>`, `llm-prompt-rewriter`):

```bash
uv run oac improve agents:registry \
    --target primary --config prod \
    --criteria criteria.yaml \
    --mutators identity,prompt-suffix:"Name trade-offs explicitly.",llm-prompt-rewriter \
    --evaluator myproj.evals:score \
    --max-iters 3 --frontier 3 --output ./improved
```

`--evaluator` is `module:callable` taking a `ComponentVersion` and
returning a metrics dict (e.g. `{"score_floor:by_name:length": 0.8}`).
The default is a no-op that returns `{"pass_rate": 1.0}` — fine for
plumbing checks, useless for real optimization.

For full control use the Python API (`IterativeLoop`) — see
`examples/20_optimization_run/improve_run.py` for a complete run with
`OpencodeMutatorClient` as the optimiser, and
`examples/26_promote_and_reload/run_cycle.py` for the whole
compile → benchmark → improve → promote → re-benchmark cycle. To invoke
each candidate as a real opencode session, use the bundled
`OpencodeRunner` + `write_test_variant_md` + `build_parent_mimic_prompt`
primitives instead of hand-rolling subprocess code.

## 4. Inspect snapshots

Round winners are written as JSON snapshots under
`improved/<component>/<short_hash>.json` (`write_round_winners`). Each
carries the mutated definition, its content hash, parent hash, author
(which mutator produced it), and metrics. Inspect one without promoting:

```bash
uv run oac promote improved/primary/<hash>.json --show
```

## 5. Promote the winner and close the loop

```bash
uv run oac promote improved/primary/<hash>.json          # → .oac/promoted/
uv run oac promote improved/primary/<hash>.json --class fast   # per-class slot
```

Promotion alone changes nothing — your registry must opt in by
registering through `register_with_improvements`:

```python
agent_id = reg.register_with_improvements(
    "primary", baseline_definition,
    ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    project_root=PROJECT_ROOT,
)
```

The merge walks the whole composable tree — the agent, each skill, each
tool reachable through skill workflow steps, every `extra_tools` entry —
applying any promoted snapshot and passing everything else through at
baseline (`examples/27_composable_improvements`). Promotion is
section-aware: definitions using `prompt_sections` re-derive
`system_prompt` from the improved sections. The next
`uv run python build_agents.py` (or `oac compile`) ships the winner.

## 6. Avoid the scoring pitfalls

These are the failure modes that have actually burned real fleets:

- **Skip infra failures — never score them 0.** A contended local vLLM
  timing out, or an opencode `{"type":"error"}` event (e.g.
  `Agent not found`) parsed as empty text, looks identical to "the model
  produced nothing" and floors the scoreboard at zero. `OpencodeRunner`
  surfaces error events on `result.error` and retries; make your
  evaluator treat them as skips, not quality signal.
- **Stochastic agents need multi-sample evaluation.** One sample per
  probe mis-ranks candidates; average several runs before comparing.
- **Optimize the real outcome, not text plausibility.** If delivery
  happens through a tool call or artifact, a text-judging loop will
  polish prose while silently dropping the load-bearing side-effect.
  Gate every evaluator on the production contract with `contract_gate`
  (predicates: `require_tool_called`, `require_any_tool_called`,
  `require_artifact`, `require_subagent_dispatched`, `all_of`) so
  undelivered candidates score 0. Full write-ups:
  [optimize the real goal, not text correctness](../lessons/optimize-the-real-goal-not-text-correctness.md)
  and [thinking models and opencode scoring](../lessons/thinking-models-and-opencode-scoring.md).

To tune several model variants at once, namespace each loop's
workspace, ports, snapshots, and promoted dir per target model and run
them in parallel — see
[variants and profiles](../guides/variants-and-profiles.md) for
per-class loops (`run_per_class_loops`, `oac promote --class`).

To go beyond one model dimension — tuning per **harness × model**
(opencode/pi/codex *and* the interactive tier), recording every run in
the SQLite store, browsing/rolling back with `oac versions`, and
judging with an LLM — see
[optimization targets](optimization-targets.md); the full flow runs
offline in `examples/85_matrix_live_chat/`.
