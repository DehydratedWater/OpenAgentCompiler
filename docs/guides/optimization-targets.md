# Optimization Targets: Adapting One Agent to Every Harness and Model

The framework's central promise is *define agents once — with tests and
benchmarks — then adapt them automatically to wherever they run*. This
guide covers the machinery that closes that loop: **optimization
targets** (the harness × model matrix), **harness-agnostic evaluation**,
the **interactive tier as a target**, per-target **promotion slots**,
the **run store** that keeps the history observable, and the
**`oac versions`** CLI that manages what's loaded.

The end-to-end demonstration is
[`examples/85_matrix_live_chat/`](https://github.com/DehydratedWater/OpenAgentCompiler/tree/main/examples/85_matrix_live_chat/).

## Why per-target tuning exists

The same logical agent renders differently and behaves differently on
each runtime:

- a small fast model wants terse, imperative prompts; an analytical
  model earns its cost with room to reason;
- opencode, pi, and codex each render workflow/permission scaffolding
  differently, so the same prompt text lands differently;
- the interactive tier (`render_interactive_prompt`) strips worker
  scaffolding entirely — a prompt tuned against a compiled harness was
  judged on a rendering the realtime agent never sees.

One winner cannot fit all of those. A **target** names one cell of the
matrix and gets its own loop, winners, and promotion slot.

## `OptimizationTarget` and `run_per_target_loops`

```python
from open_agent_compiler.improvement import (
    OptimizationTarget, run_per_target_loops, targets_from_split_profile,
    open_store,
)

targets = targets_from_split_profile(["opencode", "pi"], SPLIT)   # 2×2 cross product
targets.append(OptimizationTarget(harness="interactive"))

results = run_per_target_loops(
    baseline=baseline_version,            # ComponentVersion of the agent
    mutators=[...],                       # same mutators as any loop
    criterion=criterion,
    targets=targets,
    evaluator_factory=make_evaluator,     # target -> Evaluator (below)
    output=Path("improved"),
    store=open_store(project_root=HERE),  # observability (below)
)
```

Each target runs one `IterativeLoop` over a baseline stamped with the
target's `model_class` and a `_oac_meta.target` marker. Target keys are
`<harness>+<class>` (`"pi+fast"`) or bare `<harness>`
(`"interactive"`). Snapshots land under
`improved/<component>/<target-key>/`.

`run_per_class_loops` still exists — it is the special case of a single
implicit harness.

## The evaluator per target

`evaluator_factory(target)` returns the loop evaluator for that cell.
Three standard shapes:

### 1. Compiled harnesses — `HarnessRunner`

The live leg is no longer hard-wired to opencode. `harness_eval`
defines a `HarnessRunner` protocol with bundled implementations —
`OpencodeRunner`, `PiRunner`, `CodexRunner` — resolved by dialect name:

```python
from open_agent_compiler.improvement import get_runner

def make_evaluator(target):
    runner = get_runner(target.harness, build_dir_for(target))
    def evaluate(version):
        # compile the candidate into build_dir_for(target), then:
        result = runner.run(agent_name="summarizer", prompt=PROBE_PROMPT)
        if result.error:                  # harness failure ≠ empty answer
            return {"pass_rate": 0.0}
        return score_with_judge(result.final_text())
    return evaluate
```

Every runner exposes `final_text()`, `error`, and `succeeded`; richer
introspection (opencode's event-stream parsing, dispatch chains,
blocked-tool details) stays on the concrete result types. Register your
own harness with `register_runner("myharness", factory)`.

Runners handle each harness's trust model for you: build trees are
compile output, not git repositories, so `CodexRunner` passes
`--skip-git-repo-check` by default (set `skip_git_repo_check=False` to
opt out) the same way `PiRunner` passes `--approve`.

### 2. The interactive tier — `build_interactive_evaluator`

The realtime runner is one more target. Candidates are scored by
actually running them through `run_interactive` — the same in-process
loop the LangChain / PydanticAI bindings sit next to:

```python
from open_agent_compiler.improvement import Probe, build_interactive_evaluator
from open_agent_compiler.model.core.test_model import LLMJudgeEvaluator

evaluator = build_interactive_evaluator(
    probes=[Probe(
        probe_id="tone",
        payload="summarize this ticket",
        evaluators=(LLMJudgeEvaluator(criteria="concise and actionable"),),
    )],
    spec_factory=lambda defn: build_interactive_spec(
        agent=baseline_agent.model_copy(update={"system_prompt": defn["system_prompt"]}),
        live_profile=LIVE,
    ),
    tool_runner=my_runner,
    judge=my_judge,          # powers llm_judge probes (below)
    client=None,             # None = the spec's live provider; pass a
                             # scripted ChatClient for the offline gate tier
)
```

Outcomes carry both the final text and the `ToolCallRecord`s, so every
standard evaluator kind applies (substring, tool_called, path order,
llm_judge, …) and the metric names (`pass_rate` / `score_floor` /
`score_mean` / `score_floor:by_name:<probe>`) match branch/autoresearch
— criteria, contract gates, charts, and promotion work unchanged.
`score_interactive_spec` is the loop-free half: benchmark one spec in
CI and assert the promoted variant still clears its floor.

### 3. LLM-as-judge

Deep, rubric-based scoring uses the `llm_judge` evaluator kind
anywhere probes appear (interactive evaluator, autoresearch callables,
branch tests, agent tests). A judge is any object with
`judge(criteria, target, *, model) -> {"pass": bool, "score": float,
"reasoning": str}` — `AnthropicJudge` ships for live runs, `StubJudge`
for deterministic gates. The *mutator* side can be LLM-backed too
(`LLMPromptRewriter` via `MutationContext(llm=...)`), giving the full
propose-with-LLM / judge-with-LLM loop.

## Promotion slots and resolution

`oac promote` gained a `--target` slot; the resolution chain at compile
time is **target → model_class → default** (inside each client bucket):

```bash
uv run oac promote improved/summarizer/pi+fast/LATEST.json --target pi+fast
```

```
.oac/promoted/summarizer__pi+fast.json      ← wins for target="pi+fast"
.oac/promoted/summarizer__fast.json         ← fallback for any *+fast target
.oac/promoted/summarizer.json               ← shared default
```

In the registry factory, pass the target you are compiling for:

```python
agent = apply_promoted_to_tree(agent, project_root=HERE,
                               target="pi+fast", model_class="fast")
```

A partially-tuned matrix degrades gracefully — untuned targets inherit
the class winner or the shared default, and a fresh project compiles
from the Python baseline.

## The run store: observability without file spray

Intermediate loop history belongs in a database, not in hundreds of
JSONs. `open_store()` opens SQLite at `.oac/improvement.db` (or any
`sqlite:///` URL; other schemes plug in via `register_store_scheme` and
the small `RunStore` protocol):

```python
store = open_store(project_root=HERE)
run_per_target_loops(..., store=store)          # records every round/candidate
CompileScript(..., store_url="sqlite:///.oac/improvement.db")  # records builds
promote(snapshot, HERE, target="pi+fast", store=store)         # records history
```

With a store attached, per-target loops write **only the finalized
best-winner snapshot** per target — the single JSON that gets promoted,
loaded, and version-controlled — while every intermediate candidate,
score, and lineage edge stays queryable (`store.runs()`,
`store.candidates()`, `store.best_candidate()`, or plain `sqlite3` /
Datasette on the three flat tables).

## Managing loaded versions: `oac versions`

```bash
oac versions list summarizer                     # history + which is loaded (*)
oac versions show summarizer 3fa9c2              # one candidate in full
oac versions load summarizer 3fa9c2 --target pi+fast
oac versions unload summarizer --target pi+fast  # baseline passes through again
oac versions rollback summarizer --target pi+fast  # previous promotion
oac versions apply-source summarizer agents.py   # make the winner the checked-in baseline
```

`load`/`unload` manage the promoted JSON slots; `rollback` walks the
store's promotion history; `apply-source` rewrites the `system_prompt`
literal of the matching `AgentDefinition` **inside your Python file**
(ast-located, span-spliced, syntax-validated) for when an improvement
should graduate from overlay to baseline.

## Whole-tree optimization

Optimizing three connected agents is not one loop — it is a small fleet:

- **Leaf agents** — one per-target loop each (above).
- **Orchestrator routing** — `build_branch_loop`
  (`improvement/branch.py`) turns the branch tests (does the
  orchestrator chain the right subagents in the right order?) into the
  loop's evaluator, so the same prompt mutators tune *routing*. Its
  winners promote under `branch:<entry>` and
  `apply_promoted_to_agent(consider_branch=True)` applies whichever of
  the leaf/branch promotions scored higher.
- **Scale** — wrap every loop in `ImprovementUnit`s and hand them to
  `run_fleet` (`improvement/fleet.py`): parallel execution, per-unit
  error isolation, batch promotion over thresholds, and `namespace=`
  isolation so the same component tuned for several targets never
  collides.

Model routing is itself learnable: `model_class` is a promotable field,
so a mutator that flips it lets the loop discover that an agent belongs
on a different preset.

## See also

- [`examples/85_matrix_live_chat/`](https://github.com/DehydratedWater/OpenAgentCompiler/tree/main/examples/85_matrix_live_chat/) — the full flow, offline-runnable
- [The Improvement Loop](improvement-loop.md) — single-loop fundamentals
- [LangChain Runtime Agents](langchain-runtime.md) — the tier the interactive evaluator scores
- [Native tool calling](native-tools.md) — per-harness native tool emission
