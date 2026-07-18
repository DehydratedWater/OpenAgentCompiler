# 31 spawn-agent — typed [agent 1] → tool → [agent 2] composition

Demonstrates Phase 21's `SpawnAgentTool`. The parent agent calls
the tool with `(agent_name, prompt, context)`; the tool shells out
to `opencode_manager.py run --agent ...` and returns a TaskHandle
(running, for async spawns) or the captured Output (for blocking
spawns).

## Run the demo

```bash
uv run python examples/31_spawn_agent/spawn_demo.py
```

Two paths are shown:

1. **Synchronous spawn** — the coordinator awaits the worker. Useful
   for short workers (few seconds) where the caller wants the result
   immediately.
2. **Asynchronous spawn** — the coordinator gets back a TaskHandle
   with `status='running'` + `poll_url`. The worker runs detached;
   the caller polls (or hands the URL to the user) later.

`subprocess.run` and `subprocess.Popen` are mocked so the script
runs without needing the opencode binary. In a real deployment
those calls hit the actual dispatcher.

## When to use SpawnAgentTool vs Task-tool subagents

| Use SpawnAgentTool when… | Use Task subagent when… |
|---|---|
| Worker has its own primary identity, own session, own subagents. | Worker is a one-shot child in the parent's session. |
| Fan-out N parallel calls, drain via polling. | Single delegation, parent awaits inline. |
| Worker is long-running. | Worker completes in seconds. |
| Worker needs its own opencode-server connection. | Worker shares the parent's. |

## Composition pattern in code

```python
out_a = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="research-leg-a", prompt="…", spawn_async=True,
))
out_b = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="research-leg-b", prompt="…", spawn_async=True,
))
# Two parallel agents now running. Drain via the FastAPI scaffold:
#   GET /runs/{out_a.task.run_id}/await
#   GET /runs/{out_b.task.run_id}/await
```

See the `tool-variants` skill (Pattern 6) for variations and
example 50_primary_dispatch for the bash-allowlist form of the
same dispatch pattern.
