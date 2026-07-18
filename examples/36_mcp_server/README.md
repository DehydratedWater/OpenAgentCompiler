# 36 mcp-server — expose compiled agents over MCP

Demonstrates Phase 24's `--with-mcp-server` flag. With it on,
`oac init --template=full --with-mcp-server` generates an MCP server
alongside the FastAPI service. Both surfaces share the same
`dispatch_run`, so calling modes / variants / retry chains behave
identically.

## Run

```bash
uv run python examples/36_mcp_server/show_scaffold.py
```

Scaffolds a `--with-mcp-server` project into a tempdir and prints
the generated files so you can read the wiring end-to-end.

## What gets generated

`app/mcp_server.py` — a FastMCP server that:
- Auto-discovers every compiled agent under `build/.opencode/agents/`
  via `list_compiled_agents()`.
- Registers each as one MCP tool whose arguments mirror
  `AgentRunRequest` (prompt, mode, variant, retry, context, etc).
- Each tool's handler calls `dispatch_run` with the same
  `with_persistence` flag the FastAPI uses, so MCP-triggered runs
  land in the `runs` table alongside HTTP-triggered runs.

`mcp_server_run.py` — stdio entry point:

```bash
uv run python mcp_server_run.py
```

Point any MCP-aware client (another opencode session, Claude
Desktop, a custom orchestrator) at that command. The client sees
one tool per compiled agent.

`pyproject.toml` gets `"mcp>=1.0.0"` added to the dependencies.

## Calling modes work identically over MCP

```python
# An MCP client invoking the 'research' agent in async mode with a
# retry chain — same shape as the FastAPI POST body.
result = await mcp_client.call_tool("research", {
    "prompt": "summarise X",
    "mode": "async",
    "variant": "fast",
    "retry": {
        "steps": [
            {"variant": "fast", "when": "always", "timeout_s": 30},
            {"variant": "smart", "when": "on_failure", "timeout_s": 120},
        ],
    },
    "callback_url": "https://my-app/results",
})
```

The result mirrors the FastAPI's `AgentRunResult` — same fields,
including `resolved_variant` and `fallback_chain`. Operators read
both protocols through the same `/runs/{run_id}/detail` endpoint.

## When to use which surface

| MCP server (this) | FastAPI REST |
|---|---|
| Embedded in another agent's tool list. | External clients (cron, webhooks, UI). |
| Stdio transport for local clients. | HTTP for distributed clients. |
| Tool discovery is automatic (per agent). | Routes are documented separately. |
| Same dispatch_run / persistence. | Same dispatch_run / persistence. |

Both can run side-by-side; they're independent processes sharing
the `runs` table.
