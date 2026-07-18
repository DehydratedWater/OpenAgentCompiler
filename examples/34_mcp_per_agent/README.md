# 34 mcp-per-agent — declaring different MCP servers per agent

Demonstrates Phase 12's `MCPServerDefinition` + per-server
allowlist emission. Two agents in the same compile declare disjoint
MCP server subsets:

- **slack-bot** — Slack MCP only, all tools allowed.
- **pr-reviewer** — GitHub MCP only, restricted to `read_pr`,
  `list_issues`, `list_files`.

## Run it

```bash
uv run python examples/34_mcp_per_agent/agents.py
```

Output:

```
=== primary (slack-bot) ===
permission.mcp = {
  "slack": "allow"
}

=== reviewer (pr-reviewer) ===
permission.mcp = {
  "github": {
    "*": "deny",
    "read_pr": "allow",
    "list_issues": "allow",
    "list_files": "allow"
  }
}
```

Each agent only carries its declared servers. `slack-bot` cannot
talk to GitHub; `pr-reviewer` cannot merge or create issues even
on its allowed server — the per-tool allowlist makes
read-only access the default for any non-listed tool.

## Pattern in code

```python
AgentDefinition(
    ...,
    mcp_servers=[
        MCPServerDefinition(name="slack"),                  # all tools
        MCPServerDefinition(
            name="github",
            allowed_tools=["read_pr", "list_issues"],       # restricted
        ),
    ],
)
```

Legacy `ToolPermissions(mcp=True)` (the boolean toggle) still works
when no `mcp_servers` are declared — it produces the catch-all
`permission.mcp: allow`. When both are set, per-server inventory
supersedes the boolean.

See `authoring-agents` for the full ToolPermissions story.
