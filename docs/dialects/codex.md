# Codex Dialect

This document describes the Codex dialect implementation in
open-agent-compiler, which compiles agent definitions into
[custom agents](https://developers.openai.com/codex/subagents) for the
OpenAI Codex CLI.

## Overview

The Codex dialect generates `.codex/agents/<name>.toml` files — Codex's
custom agent format, one agent per file. Each file contains:

- **`name`** — the identifier Codex uses when spawning or referencing the
  agent
- **`description`** — when Codex should use this agent
- **`developer_instructions`** — the agent's behavior: system prompt,
  rendered workflow, security policy, subagent and skill documentation
- **`model`** / **`sandbox_mode`** — standard Codex config keys
- optional **`[mcp_servers.<name>]`** tables

Alongside the agent files, the compiler writes an **`AGENTS.md`** index at
the target root so a Codex session started in the build tree knows which
custom agents exist and when to delegate to them (Codex reads `AGENTS.md`
before doing any work).

## Compilation

Compile agents for Codex using the `--dialect codex` flag:

```bash
uv run oac compile myproj.agents:registry --config prod --target build --dialect codex
```

Or programmatically:

```python
from open_agent_compiler.compiler.script import CompileScript

script = CompileScript(
    target=Path("./build"),
    factory=my_registry_factory,
    config="prod",
    dialect="codex",  # ← compile for Codex
    clean=True,
)
result = script.run()
```

This produces:

```
build/
├── AGENTS.md                 # index of compiled agents
├── .codex/
│   └── agents/
│       ├── orchestrator.toml
│       ├── summarizer.toml
│       └── critic.toml
└── scripts/                  # backing scripts for extra_tools
```

## Codex Agent Format

### TOML Fields

| Field | Source | Description |
|-------|--------|-------------|
| `name` | slot name + postfix | Agent identifier for spawning/referencing |
| `description` | `agent_definition.header.description` (falls back to `usage_explanation_short`) | When Codex should use this agent |
| `developer_instructions` | `system_prompt` / workflow / policy / subagents / skills | The composed agent behavior |
| `model` | `model_parameters.model_name` | Model identifier (e.g., `gpt-5.2`) |
| `sandbox_mode` | Derived from `tool_permissions` | `read-only` or `workspace-write` |
| `[mcp_servers.<name>]` | `agent_definition.mcp_servers` | url-based servers only (see limitations) |

### Sandbox Mode Instead of Tool Allowlists

Codex has no per-agent tool allowlist (unlike opencode's `permission:`
block or pi's `tools:` frontmatter). Filesystem/network boundaries come
from `sandbox_mode`, which the compiler derives from `tool_permissions`:

| `tool_permissions` | `sandbox_mode` |
|--------------------|----------------|
| `None` (unset) | `workspace-write` (Codex's default posture) |
| explicit, `write=False` and `edit=False` | `read-only` |
| explicit, `write=True` or `edit=True` | `workspace-write` |

Explicit permissions also emit a SECURITY POLICY block into
`developer_instructions` so the prompt and the sandbox stay in sync.

### Body Content

`developer_instructions` mirrors the pi dialect's markdown body:

1. **Header**: `# <agent_name>`
2. **Usage explanation**: fallback only, when the agent has neither
   `system_prompt` nor `workflow`
3. **System prompt**: prepended before the workflow when both are set
4. **Workflow**: rendered workflow steps (when `workflow` is non-empty),
   including `TODO.md` bookkeeping per `todo_mode` (strict/lazy/none)
5. **SECURITY POLICY**: allowed/forbidden actions derived from
   permissions, subagents, and skills
6. **Available Tools**: docs for `extra_tools`, invocable via the shell
   (their backing scripts are written to `scripts/` in the build tree)
7. **Available Subagents**: delegation targets (see below)
8. **Skills**: skill documentation

## Subagent Delegation

Codex has **no explicit spawn tool** — it orchestrates subagent spawning
when the prompt or project instructions ask for it. The compiled
instructions therefore phrase delegation in natural language:

```markdown
## Available Subagents

You can delegate work by spawning the following custom agents as subagents:

- **summarizer** (subagent): Compress text into one paragraph.
- **critic** (subagent): Argue against the user's claim.

Example: spawn the `summarizer` agent with the task description as its
prompt, wait for it to finish, and use its result.
```

Every referenced subagent is compiled as a sibling `.toml` file in
`.codex/agents/`, so Codex can resolve the names at runtime. The
generated `AGENTS.md` reinforces the delegation targets at the project
level.

## Running Compiled Codex Agents

After compilation, start Codex in the build tree:

```bash
cd build
codex "Summarize and critique this claim: ..."
```

Codex picks up `AGENTS.md` and `.codex/agents/*.toml` automatically. To
address a specific custom agent, ask for it by name ("spawn the
`summarizer` agent on this text").

## Differences from the Other Dialects

| Feature | OpenCode | Pi | Codex |
|---------|----------|----|-------|
| Output | `.opencode/agents/*.md` | `.pi/agents/*.md` | `.codex/agents/*.toml` + `AGENTS.md` |
| Agent format | YAML frontmatter + markdown | YAML frontmatter + markdown | TOML with `developer_instructions` |
| Tool restriction | `permission:` block | `tools:` allowlist + `disallowed_tools:` | `sandbox_mode` (read-only / workspace-write) |
| Subagent spawning | Task tool | `Agent()` tool (pi-subagents) | natural-language delegation |
| Todo tracking | `todoread`/`todowrite` tools | `TODO.md` conventions | `TODO.md` conventions |
| MCP servers | `permission.mcp.<name>` | not mapped (warning) | `[mcp_servers.<name>]` for url servers; stdio warns |
| Runtime extensions | — | pi-subagents + pi-permission-system | none (built into Codex CLI) |

## Limitations

- **stdio MCP servers are incomplete**: `MCPServerDefinition` without a
  `url` compiles with a `UserWarning` — Codex needs a `command` entry the
  OAC model doesn't carry; add it to the emitted table manually.
- **Per-server MCP tool allowlists are not enforced**: `allowed_tools`
  produces a compile warning; Codex has no equivalent restriction key.
- **No per-tool allowlist**: `tool_permissions` collapses to
  `sandbox_mode` plus the advisory SECURITY POLICY block — finer-grained
  denial (e.g. "read but never edit inside a writable sandbox") is prompt
  guidance only.
- **`model_reasoning_effort` is not emitted**: the OAC model has no
  reasoning-effort field yet; add it manually to compiled files if needed.
- **Model names pass through verbatim**: `model_parameters.model_name` is
  not translated — use Codex-valid model identifiers in the profile you
  compile for codex (e.g. via a `SplitProfile` preset).
- `workspace` renders as a prompt instruction only — there is no
  `workspace_io.py`-style enforcement script for codex.

## See Also

- [Codex subagents documentation](https://developers.openai.com/codex/subagents)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [Pi dialect](pi.md) — the closest sibling dialect (same body
  composition, different spawn/permission model)
