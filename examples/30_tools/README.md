# 30 tools — bash + JSON-schema tool variants

A `time-tool` ScriptTool wired into two agents:

| Slot file | `tool_format` | What lands in the frontmatter |
|---|---|---|
| `primary.md` | `both` | bash allowlist `uv run scripts/time_tool.py *` AND a `custom_tools` block with the tool's JSON schema |
| `json-variant.md` | `json` | only the `custom_tools` block (no bash permission for the tool) |

## What this example exercises

- **ScriptTool** — `scripts/time_tool.py` is a real Pydantic-typed
  `ScriptTool[TimeInput, TimeOutput]` with execute() + mock_response().
- **ToolDefinition** with both `bash_tool` and `json_tool` contracts —
  same handler, two invocation surfaces.
- **`AgentDefinition.default_tool_format`** picker that decides which
  contract(s) emit per agent.
- **`MockResponse`** on the tool — `oac test` and downstream tests
  invoke the mock instead of running the script.
- **`SkillDefinition`** that groups the tool inside a workflow with
  per-step rules and references.
- **`AccessProfile`** primitive (no resources here; the example
  declares an empty `prod` and a `ci` profile with a mock-only
  resource so the surface is visible).
- **`ScriptDefinition`** + `ToolScriptDefinition` — auto-copy of the
  handler script into `build/scripts/`.

## Build

```bash
uv run python examples/30_tools/build_agents.py
```

Produces:
```
build/.opencode/agents/primary.md
build/.opencode/agents/json-variant.md
build/scripts/time_tool.py             (copied from examples/30_tools/scripts/)
```

## Invoke

```bash
cd examples/30_tools/build
opencode run --agent primary "What time is it in CET (offset +1)?"
opencode run --agent json-variant "What time is it?"
```

The agent calls `time-tool` (via bash for `primary`, via the JSON
tool surface for `json-variant`), gets back an ISO-8601 timestamp, and
includes it in the reply.

## Inspect the compiled frontmatter

```bash
head -25 build/.opencode/agents/primary.md
head -25 build/.opencode/agents/json-variant.md
```

The `primary.md` frontmatter has both:
- `permission.bash["uv run scripts/time_tool.py *"]: allow`
- a `custom_tools` array entry for `time-tool` with its inputSchema

The `json-variant.md` only has the `custom_tools` entry — bash isn't
allowed for that agent.
