# The opencode dialect

opencode is the default compile target: `CompileScript(dialect="opencode")`
or plain `oac compile` with no `--dialect` flag. This page walks through
what the compiler emits, how agent modes and permissions map, and how to
run the result with `opencode run`. New here? Build something first with
[your first agent](../getting-started/first-agent.md).

## 1. What gets emitted

Compiling a resolved tree into `build/` produces:

```
build/
  .opencode/agents/<slot><postfix>.md   # one file per template slot (per variant)
  scripts/                              # tool scripts + bundled infra
```

- **Agent markdown** — one file per `TemplateSlot`, named
  `<slot><postfix>.md` (postfix comes from the `VariantSpec`, empty for
  the default variant; slot names containing `/` become subdirectories).
- **`scripts/`** — two copy passes: per-tool scripts declared on each
  `ToolDefinition.json_tool.tool_scripts`, then bundled infrastructure
  scripts copied only when the tree needs them: `subagent_todo.py`
  (workflow + todo tracking), `workspace_io.py` (agents with a
  `workspace`), `opencode_manager.py` (primary-mode subagent dispatch).
- **`opencode.json`** — the compiler itself doesn't write one; the
  project root you run from should carry it (the `oac init` scaffold
  generates it) so opencode treats the directory as a project and finds
  providers/MCP servers. Per-client personalized builds emit one via
  `write_personalized_opencode_json` (top-level `mcp` servers merged
  with your base config).

## 2. The frontmatter shape

Each agent file is YAML frontmatter + the composed prompt body:

```yaml
---
description: Routes user input through summarizer + critic.
model: zai-coding-plan/glm-4.5-air
mode: primary            # or subagent
permission:
  '*': deny
  task: allow
  bash:
    'uv run scripts/echo.py *': allow
tool:
  read: false
  write: false
  edit: false
  task: true
  todoread: false
  todowrite: false
  mcp: false
  bash: true
---
```

The body contains the agent name and description, the composed prompt
(system prompt, workflow steps, tool docs), a `## Your Skills` section,
subagent invocation snippets, and a generated `## SECURITY POLICY`
section that mirrors the `permission:` block in prose — enforcement and
agent awareness stay in sync. Tools that opt into the JSON contract
additionally get `custom_tools:` schema blocks in the frontmatter.

## 3. Primary vs subagent modes

The registry derives the mode from the slot name: the slot named
`primary` compiles with `mode: primary`; every other slot compiles as
`mode: subagent`.

- **Subagent mode** (default for children) — invoked by a parent via the
  Task tool (`subagent_type: "<name>"`). The parent automatically gets
  `permission.task: allow` when it declares subagent-mode children.
- **Primary mode** — directly invocable with `opencode run --agent`.
  A parent invokes primary-mode children through the bundled
  `scripts/opencode_manager.py`, and gets the matching bash allowlist
  entry (`uv run scripts/opencode_manager.py run --agent *`) compiled in.

## 4. Dual-compile twins

Set `also_compile_as_primary=True` on a `TemplateSlot` (or the
`AgentDefinition`) and the compiler emits a second file,
`<slot><postfix>-primary.md`, with primary-mode permissions — the same
agent reachable both as a Task-tool subagent *and* directly via
`opencode run --agent <name>-primary` (or from another primary through
`opencode_manager.py`). Slots already in primary mode skip the twin to
avoid colliding with themselves.

## 5. Permission mapping

`generate_permissions` compiles a default-deny stance per agent:

| Source on the definition | Emitted |
|---|---|
| (always) | `permission: {'*': deny}`; bash and skill default-deny |
| Bash tool `allowed_commands` (falls back to `positive_examples`) | `permission.bash.<pattern>: allow` |
| JSON tool | `permission.<tool-name>: allow` |
| `skills` | `permission.skill.<name>: allow` |
| Subagent-mode children | `permission.task: allow` |
| Primary-mode children | bash allowlist entry for `opencode_manager.py` |
| Primary agent with workflow + `todo_mode != "none"` | `todoread`/`todowrite: allow` |
| `tool_permissions=ToolPermissions(read/write/edit/mcp)` | matching `allow` entries + `tool:` toggles |
| `mcp_servers=[MCPServerDefinition(name=..., allowed_tools=[...])]` | `permission.mcp.<server>` — `allow`, or a nested `{'*': deny, <tool>: allow}` block when `allowed_tools` is set |

## 6. The tools map is `{name: bool}` — not a permission map

opencode's frontmatter `tool:` block (and the `tools` key in a
per-client `opencode.json`) is an enable/disable **switch of booleans**.
Granular allowlists live *only* under `permission:`. opencode ≥ 1.17
treats a dict value in the tools map as "disabled" and silently strips
the tool — an agent compiled with `tool.bash: {<allowlist>}` ends up
with *no bash at all* and can only narrate; a list value makes opencode
reject the whole config, which zero-scores every run built on it. The
compiler therefore collapses any nested allowlist in the tools map to
`true` and keeps the real allow/deny rules in `permission:`. If you
post-process emitted configs, preserve this invariant.

## 7. Run it

```bash
uv run oac compile agents:registry --config prod --target build --clean
cd build
opencode run --print-logs --agent primary "Summarize this: ..."
```

Practical notes (see also the troubleshooting section of the
[developer guide](../dev-guide.md)):

- Run from the directory that carries `opencode.json` so agents are
  discovered; agent name = the file stem under `.opencode/agents/`.
- Some opencode versions deadlock at startup without `--print-logs`.
- Give concurrent runs private `XDG_DATA_HOME` dirs or they hit
  `database is locked`.
- If an agent flails on a custom tool, put the tool's exact command
  verbs in its usage docs before blaming the model.

Compiled agents are also the workers behind the
[interactive tier](../guides/interactive-tier.md) and the units the
[improvement loop](../guides/improvement-loop.md) optimizes. For other
targets see [claude-code](claude-code.md) and [pi](pi.md), or list
what's registered with `oac info --dialects`
([CLI reference](../reference/cli.md)).
