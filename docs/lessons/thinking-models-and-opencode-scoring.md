# Lesson: scoring agents via opencode (the "mass-zero" trap)

**TL;DR** — Score an agent only as a **full opencode session, run to
auto-termination, in a DISCOVERABLE project context** (a stable dir with
`opencode.json` and a **flat-named** agent file), and make the runner **surface
opencode error events**. The real mass-zero cause is almost never the model — it
is `Agent not found` (or another opencode error) being silently swallowed as
"empty assistant text" and scored 0.

## Symptom

A full-fleet autoresearch run promotes a tiny fraction of agents (observed:
**6 of 137**, ~65% scoring exactly `0.000`), even though the agents are fine.
Spot-checks show the agent "ran" but produced **no visible output**.

## Root cause (the one that actually bit us)

The autoloop compiled each candidate into an **ephemeral temp dir** with a
**nested / slashed** agent name (`persona/responding-primary` at
`.opencode/agents/persona/responding-primary.md`). opencode did **not** discover
it — it only loaded its built-ins and emitted:

```
{"type":"error","error":{"data":{"message":
  "Agent not found: \"persona/responding-primary\". Available agents: build, explore, general, plan"}}}
```

opencode reports this as an **error event while still exiting 0**, and the
runner's parser returned `""` for it. The judge then scored the empty string 0.
So a whole fleet of **agent-discovery** failures looked like "the model returns
nothing" — and sent us chasing a non-existent thinking/model bug for hours.

A mature v3 deployment runs **perfectly** on the same vLLM +
opencode + thinking-on, because it runs from a **stable project root** with
**flat-named** agents and a **warm `opencode` server** (its
`scripts/opencode_manager.py`). Verified: a v3 agent from v3's root is 3/3 OK
(11–12k bytes); the same model from an ad-hoc temp dir is `Agent not found`.

## The fix (approach A — mirror `opencode_manager`)

1. A **stable workspace** carrying `opencode.json` so opencode treats it as a
   project (reliable discovery).
2. Install candidates **FLAT-named** (`cand_<hex>.md`), never nested/slashed.
3. A **warm dedicated opencode server** + a **discovery warmup** (run a throwaway
   flat candidate until it resolves) so the server's rescan lag doesn't 0 the
   first candidate of a run.
4. **Surface opencode error events** in the runner — `{"type":"error"}` →
   `result.error`, never empty text. This single safeguard would have caught the
   whole thing on day one.

Result: the runner went from ~50–70% "empty" (= not-found) to fully reliable,
thinking left ON.

## Secondary note: thinking models

Qwen3.x is a hybrid reasoning model. It *can* spend a turn "thinking" and return
empty visible content if starved of tokens, and `chat_template_kwargs.
enable_thinking=false` (request body) is the only reliable per-call disable —
which **opencode drops**. But with reliable discovery + an adequate token budget
+ a warm server, thinking-on is reliable in practice. **Do not disable thinking
to "fix" empties before confirming the empties aren't actually swallowed
opencode errors.** And never bypass opencode with a bare `/chat/completions`
call — that is not a test of the agent (no tools, no runtime); it mis-ranks
candidates.

## Pre-run checklist

1. Run a plain agent probe ~10× from the SAME context the autoloop uses. If any
   come back blank, print `result.error` — it is almost certainly
   `Agent not found` / a provider error, not the model.
2. Score only as full opencode sessions in a discoverable project (stable dir +
   `opencode.json` + flat agent name + warm server).
3. Never let an opencode error event pass as empty assistant text.
4. Use concrete, fully self-contained probes (input data inline); never
   "demonstrate your core function" prompts.

See the `improvement-loop` skill (`open_agent_compiler/skills/content/improvement_loop.py`) for
the short version.
