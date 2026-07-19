# Native Tool Calling

By default a compiled agent invokes its ScriptTools **via bash**
(`python scripts/<tool>.py --command ... --field value`) — universally
portable, but the model is pattern-matching a shell command instead of
using the harness's structured tool-calling path. Every harness that
*has* a native custom-tool mechanism can do better. The
`--native-tools` compile option emits that native form alongside the
bash docs, bridged deterministically to the same Python script.

```bash
uv run oac compile agents:registry --config prod --target build --native-tools
```

```python
CompileScript(..., native_tools=True)
```

Only tools carrying a **json contract** (`json_tool` on the
`ToolDefinition`) participate — the JSON Schema is derived from the
ScriptTool's Pydantic `Input` model, the same derivation the `json`
tool format has always used for `custom_tools` frontmatter.

## What each harness gets

| Harness | Native mechanism | What gets emitted |
|---------|------------------|-------------------|
| opencode | TS tools in `.opencode/tool/` | One `<name>.ts` shim per tool |
| claude | none per-tool — MCP servers | `scripts/mcp_tools_server.py` + `.mcp.json` |
| codex | none per-tool — MCP servers | same server + `[mcp_servers.oac-tools]` in each agent TOML |
| pi | extension API (`pi.registerTool`) | `.pi/extensions/oac-tools.ts` registering every tool (Typebox schemas) |

### opencode: TypeScript shims

Each shim is deliberately logic-free: zod args mapped from the Pydantic
schema (scalars, enums, descriptions, optionality; nested structures
degrade to `any()` because **the Python side re-validates with the real
model** — the TS layer is permissive-but-typed, never authoritative),
and an `execute()` that pipes the args as JSON into the script's
`--json` stdin mode (which `ScriptTool.run()` has always supported):

```ts
import { tool } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"

export default tool({
  description: "Get a weather forecast.",
  args: {
    "city": tool.schema.string().describe("City name to look up"),
    "days": tool.schema.number().int().optional(),
  },
  async execute(args) {
    const proc = spawnSync("python3", ["scripts/weather.py", "--json"], {
      input: JSON.stringify(args ?? {}), encoding: "utf-8",
    })
    if (proc.status !== 0) throw new Error(proc.stderr?.trim() || `exit ${proc.status}`)
    return (proc.stdout ?? "").trim()
  },
})
```

### claude / codex: the MCP route

Claude Code and Codex have no per-tool file format; their native route
to custom tools is an **MCP server**. The compiler emits
`scripts/mcp_tools_server.py` — a FastMCP stdio server that, at
startup, imports every script in `scripts/`, finds the `ScriptTool`
subclasses, and registers each as an MCP tool **with its real Pydantic
input model** (no schema drift possible). Registration is per harness:

- **claude** — `.mcp.json` at the build root (merged, not clobbered):

  ```json
  { "mcpServers": { "oac-tools": {
      "command": "python3", "args": ["scripts/mcp_tools_server.py"] } } }
  ```

- **codex** — an `[mcp_servers.oac-tools]` stdio block appended to every
  compiled `.codex/agents/*.toml`.

The server needs `pip install mcp` in the environment that runs the
build tree (a generated-file dependency, not a framework one).

### pi

pi's native mechanism is its extension API: the compiler emits
`.pi/extensions/oac-tools.ts`, one `pi.registerTool()` per json-contract
tool with Typebox parameter schemas, each `execute()` bridging to
`python3 scripts/<tool>.py --json`. The project-local extension loads
when the project is trusted — run pi with `--approve` (what `PiRunner`
does) or approve the trust prompt once. Live-verified: a real pi
session calls the registered tool natively and returns the ScriptTool's
output.

## Choosing formats

`AgentDefinition.default_tool_format` (`bash` / `json` / `both`) and
per-tool `tool_format_overrides` still control what the *prompt*
documents. `--native-tools` is orthogonal: it adds the native
implementation for whatever carries a json contract, and the bash docs
remain as the fallback for runtimes missing node/mcp.

## See also

- [Tools guide](tools.md) — defining ScriptTools and formats
- `open_agent_compiler/compiler/native_tools.py` — the emitter
- [Optimization targets](optimization-targets.md) — tuning tools per harness
