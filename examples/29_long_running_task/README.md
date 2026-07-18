# 29 long-running-task — TaskHandle return + poll-vs-wait

Demonstrates Phase 20's TaskHandle pattern. A tool that may take
minutes returns a handle instead of blocking; the caller polls
`/runs/{run_id}/await` later.

## Run it

```bash
# Async path — returns TaskHandle with status='running' and poll_url
uv run python examples/29_long_running_task/slow_tool.py

# Blocking path — returns TaskHandle with status='success' + result
uv run python examples/29_long_running_task/slow_tool.py --blocking
```

You'll see the JSON-serialized handle, including `kind='long_running_tool'`,
`poll_url`, and an `eta_seconds` hint.

## In a real deployment

The FastAPI scaffold's runs router exposes
`GET /runs/{run_id}/await?timeout_s=N` which long-polls until the
run reaches a terminal status (`success` / `failure`) or the
timeout fires. The endpoint returns the same detail payload as
`/runs/{run_id}/detail` plus a top-level `awaited` boolean so the
caller can tell completion from timeout.

The parent agent's prompt can be patterned as:

```
1. Call slow-ingest tool — receive a TaskHandle.
2. Hand the run_id back to the user; tell them you'll resume when ready.
3. Next turn: GET /runs/{run_id}/await?timeout_s=60. If `awaited:true`,
   use the result; if `awaited:false`, tell the user it's still running.
```

See the `tool-variants` skill (Pattern 5) for variations.
