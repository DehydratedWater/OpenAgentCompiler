# Tuning a local agent fleet with the improvement loop — problems & the working process

A field report from autotuning a 137-agent fleet (GLM-5.1 teacher → Qwen-27B
student, both via opencode). The loop went from **6/137 promoted → 109/137**
once each problem below was fixed. Every one of these had ZERO test coverage at
first, which is why they recurred — so each now has a regression test and is
documented here.

## Final result

| | Start | After the fixes |
|---|---|---|
| Promoted | 6/137 | **109/137 (80%)** |
| Mean winner score | 0.116 | ~0.71 |
| Agents scoring 0 | 101 | ~10 |
| Forbidden-tool flailing | ~1800 denied calls/run | **~1** |

The remaining ~28 are inherently hard to grade single-shot (orchestrators that
dispatch, hardware/external agents that need real resources, roleplay needing a
scene) — see "non-single-shot grading" below.

## The problems, in the order they bit (symptom → cause → fix)

1. **Mass zeros that looked like a model problem.** ~65% of agents scored exactly
   0. *Cause:* the loop compiled each candidate into an **ephemeral temp dir with
   a nested/slashed agent name** (`a/b-primary`); opencode didn't discover it and
   emitted `{"type":"error","data":{"message":"Agent not found …"}}` **while
   exiting 0** — and the runner's parser returned `""` for that error, so the
   judge scored an empty string 0. *Fix:* run candidates from the real opencode
   **project root** (the dir with `opencode.json`) with **FLAT** agent names
   (`cand_<hex>.md`); and **surface opencode error events** in the runner —
   `{"type":"error"}` → `result.error`, never empty text. This single
   error-surfacing safeguard would have caught the whole class on day one.
   Don't chase a "thinking model" ghost before ruling this out.

2. **Sessions invisible to the monitored opencode.** Sessions were written to an
   isolated subdir. *Fix:* run from the project root so `XDG_DATA_HOME =
   <root>/.opencode/data` — where you watch the project in the opencode UI.

3. **Teacher hammering the provider's raw API (ToS / ban risk).** The GLM teacher
   (rewriter/judge/probe-writer) was calling `api.<provider>/chat/completions`
   directly. *Fix:* run the teacher as an **opencode agent** too
   (`zai-coding-plan/glm-5.1`), exactly like the student runs on qwen — same
   opencode path, only the model differs. No direct provider calls anywhere.

4. **Setup stalled for tens of minutes.** Synthesising a per-agent test probe via
   the teacher, 137× sequentially, before any scoring. *Fix:* **pre-synthesise
   probes in parallel and cache to disk**; persist only real probes, never
   offline fallbacks.

5. **Self-referential probes → meta-answers.** "Demonstrate your core function"
   made agents narrate a demo instead of doing the job. *Fix:* synthesise a
   **concrete, fully self-contained** task (input data inline) + an anti-meta
   guard, and grade with an LLM judge on "did it actually do the job."

6. **Tool agents dying on `ModuleNotFoundError`.** Agents run their tools as
   `python scripts/<tool>.py`; the bash tool launched the SYSTEM python (no deps,
   no `PYTHONPATH`), so the scripts died and the agent produced nothing. *Fix:*
   pass the loop's own **deps-having interpreter first on PATH** (+ `uv`,
   `opencode`) and **propagate `PYTHONPATH`** into every run.

7. **Debug-flailing on forbidden commands.** When a tool failed, the thinking
   model debug-flailed — `pip install`, `which python`, `ls`, `find`, absolute
   paths — all DENIED by the agent's allow-list, retried repeatedly (~1800
   denied calls/run), the turn wasted, the score tanked. *Fix:* a strict
   **tool-discipline guard** appended at compile time: use only your listed
   `python scripts/*.py` tools in the exact form; never inspect/install/debug the
   env or read source / glob the codebase; on a tool error, report it in one line
   and continue — don't retry variations.

8. **Orchestrators can't be graded single-shot.** Their job is a multi-step
   session that may spawn sub-agents; a one-turn judge under-scores them.
   *Fix:* **non-single-shot grading** (below).

9. **Optimising a TEXT PROXY instead of the real delivery contract.** The loop
   judged candidates on their assistant TEXT, but production delivery happens via a
   tool-call (`emit_guidance.py`) whose payload is what the user actually sees —
   the prose is invisible. The teacher's rewrites "improved" the text while
   silently **dropping the load-bearing tool-call**: optimised agents scored great
   in the loop and delivered NOTHING live (a briefing agent produced 1253 chars and
   sent nothing). *Cause:* the metric (text quality) diverged from the real goal
   (deliver via the tool), and nothing exercised the real path until live use.
   *Fix:* **optimise the real goal in context** — the evaluator gates on the
   production contract (required tool-call / emitted artifact / side-effect) and
   scores 0 when it's absent; the judge grades the *delivered payload*, not the
   prose; the teacher is told never to drop load-bearing contracts; probes + rubric
   reflect the real goal. Full writeup:
   `docs/lessons/optimize-the-real-goal-not-text-correctness.md`. Enforced by the
   `contract_gate` primitive (see "What's now tested").

## The working process (recipe)

Everything runs through opencode — student AND teacher; only the model differs.

1. Run candidates from the **opencode project root** (has `opencode.json`),
   FLAT-named into `<root>/.opencode/agents/cand_<hex>.md`.
2. **Surface opencode error events** in the runner; never let one pass as empty
   output. (Pre-flight: a plain probe should return non-empty text >95% of runs;
   if not, print `result.error` — it's almost certainly `Agent not found` /
   provider error, not the model.)
3. **Warm a dedicated opencode server** + a discovery **warmup** (run a throwaway
   flat candidate until it resolves) so the first candidate isn't mis-scored.
4. Sessions land in `<root>/.opencode/data` for live monitoring.
5. **Pre-synthesise + cache probes in parallel.**
6. Pass the **deps-having interpreter on PATH** + `PYTHONPATH` so tool subprocesses
   import their deps.
7. Append the **tool-discipline guard** so agents don't flail on forbidden
   commands or pointless filesystem exploration.
8. Model sampling = the model's recommended settings (Qwen3.x: temp 1.0,
   top_p 0.95, top_k 20, thinking ON) with an adequate token budget.
9. **Probes are concrete + self-contained**, graded by an LLM judge on outcome.

## Non-single-shot grading (orchestrators / multi-step agents)

Single-shot judge tests under-score orchestrators. Run the orchestrator as a
**full multi-step opencode session** (the whole fleet compiled in so it can spawn
sub-agents, the runtime env wired) and **judge the OUTCOME** — did the final
response fulfil the request — with the documented dispatch path as a *soft hint*,
NOT a hard path-match (orchestrators frequently do the work themselves). When the
agent acts only via tools/dispatch with no prose, show the judge the **trajectory**
(the spawned-agent chain, parsed from the `--agent` bash dispatches) so it grades
the actions. See `make_branch_judge_test` / `build_branch_evaluator` in the v4
consumer.

CAVEAT: true dispatch-*path* verification (assert it spawned the exact chain)
needs the **full production orchestration runtime** (warm `opencode_manager`
server, sandbox dirs, exact permissions) — a dedicated runtime-replication task.
Outcome-judging works today; path-verification is the remaining headroom.

## What's now tested

Regression tests pin every fix (pure/mocked, no live opencode/qwen/provider):
opencode errors surfaced not swallowed · teacher routed through opencode (no raw
API) · probe cache round-trip (fallbacks never persisted) · concrete anti-meta
probe · trajectory-aware judging · workspace = project root + flat names ·
`blocked_tool_attempts` flailing detector · `subagent_dispatch_chain` extractor ·
the non-single-shot branch outcome evaluator · the **contract gate** that forces a
candidate to score 0 when it skips the production contract (required tool-call /
emitted deliverable) so the loop optimises the real goal, not a text proxy.

See also the `improvement-loop` skill (operational recipe + the mass-zero GOTCHA),
`thinking-models-and-opencode-scoring.md`, and
`optimize-the-real-goal-not-text-correctness.md` (optimise the production contract,
not text quality).
