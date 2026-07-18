# 35 fastapi-dispatch — three calling modes + variants + retries

Demonstrates Phase 23's FastAPI abstraction layer. The scaffold's
`app/dispatch.py` (emitted by `oac init --template=full`) accepts
three calling modes, picks among compiled variants by name, and
walks a composable RetryPolicy on failure.

This example mirrors the dispatcher logic in-process so you can see
all four behaviours without needing the FastAPI server running.

## Run

```bash
uv run python examples/35_fastapi_dispatch/dispatch_demo.py
```

You'll see four sections:

1. **Three calling modes**: `sync` (block + return), `async` (return
   run_id + poll_url immediately), `fire_and_forget` (detached run
   with optional callback URL).
2. **Variant routing**: one logical name `research` maps to
   `research.md`, `research-fast.md`, `research-smart.md` etc; the
   FastAPI picks per request.
3. **Retry chain (shorthand)**: `RetryPolicy.linear(["fast", "smart",
   "external-api"])` — try each in order, each gated on previous
   failure. The demo's stub `run_fn` fails on `fast` and succeeds
   on `smart`, so the chain stops at step 2.
4. **Retry chain (hand-rolled)**: explicit `RetryStep` list with
   `when ∈ {always, on_failure, on_timeout}` conditions and
   per-step timeout / note.

## What the demo prints

```
============================================================
Retry policy — composable escalation chain
============================================================

REQUEST.retry (RetryPolicy.linear shorthand):
{
  "steps": [
    {"variant": "fast", "timeout_s": 60.0, "when": "always", "note": null},
    {"variant": "smart", "timeout_s": 60.0, "when": "on_failure", "note": null},
    {"variant": "external-api", "timeout_s": 60.0, "when": "on_failure", "note": null}
  ]
}

FINAL: status=completed variant='smart'

fallback_chain (every attempt):
[
  {"variant": "fast", "status": "failed", "return_code": 1,
   "error": "variant 'fast' failed in this scenario", "note": null},
  {"variant": "smart", "status": "completed", "return_code": 0,
   "error": null, "note": null}
]
```

## How the request maps to the real FastAPI

```bash
curl -X POST http://localhost:8002/agents/research/run \
  -H "content-type: application/json" \
  -d '{
    "prompt": "summarise X",
    "mode": "fire_and_forget",
    "callback_url": "https://my-app.example/results",
    "retry": {
      "steps": [
        {"variant": "fast", "when": "always", "timeout_s": 30},
        {"variant": "smart", "when": "on_failure", "timeout_s": 120},
        {"variant": "external-api", "when": "on_failure", "timeout_s": 300}
      ]
    }
  }'
```

The server runs the agent detached, escalates through the chain on
failure, persists every attempt to the `runs` table, and POSTs the
final AgentRunResult (with the full `fallback_chain`) to your
callback URL when the chain terminates.

## See also

- `tool-variants` skill (Phase 22) — the catalogue of tool patterns
  the agent can use *inside* a run.
- `improvement-loop` skill — how to tune which variants get
  produced in the first place (`oac improve` writes the snapshots;
  `oac promote --class <name>` promotes the per-variant winner;
  `register_with_improvements` merges it on next compile).
