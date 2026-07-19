# Pi Agent Dialect

This document describes the Pi agent dialect implementation in
open-agent-compiler, which compiles agent definitions for the
[Pi](https://pi.dev) runtime using the
[@tintinweb/pi-subagents](https://pi.dev/packages/@tintinweb/pi-subagents)
extension.

## Overview

The Pi agent dialect generates `.pi/agents/<name>.md` files that pi-subagents
can load and execute. Each file contains:

- **YAML frontmatter** declaring the agent's configuration (tools, model,
  skills, etc.)
- **Markdown body** containing the system prompt

## Runtime Requirements: Two Extensions

Compiled agents assume the pi runtime is running with **two** extensions
installed — one for subagents, one for permissions:

| Extension | Role | Install |
|-----------|------|---------|
| [`@tintinweb/pi-subagents`](https://pi.dev/packages/@tintinweb/pi-subagents) | Subagent spawning — provides the `Agent()` tool the compiled prompts reference, plus background execution, the live agent widget, skill preloading, and worktree isolation | `pi install npm:@tintinweb/pi-subagents` |
| [`pi-permission-system`](https://github.com/MasuRii/pi-permission-system) | Permission enforcement — deterministic allow/deny/ask gates for tools, bash, MCP, and skills, evaluated at tool-call time; also forwards `ask` confirmations from non-UI subagents back to the main session | `pi install npm:pi-permission-system` |

Why both matter:

- Without **pi-subagents**, every `Agent()` call in a compiled orchestrator
  prompt fails — there is no other spawn mechanism in the pi output.
- Without **pi-permission-system**, the `tools:` allowlist and
  `disallowed_tools:` frontmatter this dialect emits are not *enforced* at
  tool-call time — the SECURITY POLICY block in the prompt body becomes
  advisory text the model is merely asked to respect.

The compiler does not verify the extensions are installed (it never talks
to the pi runtime); check with `pi list extensions` before running the
compiled agents.

## Compilation

Compile agents for Pi using the `--dialect pi` flag:

```bash
uv run oac compile myproj.agents:registry --config prod --target build --dialect pi
```

Or programmatically:

```python
from open_agent_compiler.compiler.script import CompileScript

script = CompileScript(
    target=Path("./build"),
    factory=my_registry_factory,
    config="prod",
    dialect="pi",  # ← compile for Pi
    clean=True,
)
result = script.run()
```

This produces:

```
build/
└── .pi/
    └── agents/
        ├── orchestrator.md
        ├── summarizer.md
        └── critic.md
```

## Pi Agent Format

### Frontmatter Fields

| Field | Source | Description |
|-------|--------|-------------|
| `description` | `agent_definition.header.description` | Short agent description |
| `model` | `model_parameters.model_name` | Model identifier (e.g., `anthropic/claude-sonnet-4-20250514`) |
| `tools` | Mapped from tools + permissions | Comma-separated tool allowlist |
| `skills` | `agent_definition.skills[].name` | Comma-separated skill names |
| `prompt_mode` | Always `replace` | Pi agents are standalone (not appended to parent) |
| `thinking` | `model_parameters.reasoning_effort` (or a reasoning-enabled `ModelPreset`) | Thinking level (off/minimal/low/medium/high/xhigh) |
| `max_turns` | Not in OAC model | Can be added manually to compiled files |
| `memory` | Not in OAC model | Can be added manually (`project`, `local`, `user`) |
| `disallowed_tools` | From permission negation | Tools to explicitly deny |

### Tool Mapping

OAC tools are mapped to Pi's built-in tool names:

| OAC Tool | Pi Tool |
|----------|---------|
| `read` | `read` |
| `write` | `write` |
| `edit` | `edit` |
| `bash` | `bash` |
| `grep` | `grep` |
| `find` | `find` |
| `ls` | `ls` |
| `task` | `task` (pi-subagents' `Agent()` tool) |
| `todoread` | `read` (no dedicated pi equivalent) |
| `todowrite` | `write` (no dedicated pi equivalent) |

Agents always get `read` and `bash` by default. The `task` tool is added
when the agent has subagents defined.

### Body Content

The markdown body includes:

1. **Header**: `# <agent_name>`
2. **Usage explanation**: From `usage_explanation_long` — *fallback only*,
   used when the agent has neither `system_prompt` nor `workflow`
3. **System prompt**: From `system_prompt` (prepended before the workflow
   when both are set)
4. **Workflow**: Rendered workflow steps (when `workflow` is non-empty)
5. **SECURITY POLICY**: Allowed/forbidden actions derived from
   permissions, subagents, and skills
6. **Available Tools**: Docs for `extra_tools`, invocable via bash (their
   backing scripts are written to `scripts/` in the build tree)
7. **Available Subagents**: List of subagents with `Agent()` syntax examples
8. **Skills**: Skill documentation (when skills are defined)

## Workflow Rendering

When an agent has a workflow defined, it's rendered as markdown sections:

```markdown
## Workflow

Follow these steps for every incoming task:

**STEP 0 (before anything else): create a `TODO.md` file listing every workflow step below as an unchecked item. After completing each step, immediately mark it done in `TODO.md`. Never skip this bookkeeping.**

CRITICAL: YOU MUST EXECUTE ALL STEPS WITHOUT ANY USER INPUT. DO NOT STOP UNTIL YOU FINISH ALL STEPS.

---

### Step 1: Delegate

Spawn the helper subagent.

**Subagents to spawn:**

- Spawn `helper` via `Agent({ "subagent_type": "helper", "prompt": "<task description>", "description": "A helpful assistant." })`

## Final Checklist

Before submitting your final answer:

- [ ] All workflow steps completed
- [ ] Output matches the requested format
- [ ] No steps skipped
```

Todo tracking depends on `todo_mode`:

- `strict` — the explicit STEP 0 `TODO.md` bootstrap shown above, plus
  per-step "mark as complete" checklists for `marks_done` entries.
- `lazy` — a lightweight "track your progress in a todo list" note.
- `none` — no todo instructions; `marks_done` checklists are suppressed.

Steps with `evaluates` criteria render an "Evaluate the following
criteria" block (name, question, possible values) so that `routes`
always reference criteria the agent has been told to evaluate.

## Subagent References

When an agent has subagents, the compiled prompt includes:

1. **In workflow steps**: Direct `Agent()` tool calls with proper syntax
2. **Available Subagents section**: Lists all subagents with descriptions

Example:

```markdown
## Available Subagents

You can spawn the following subagents using the `Agent()` tool:

- **summarizer** (subagent): Compress text into one paragraph.
- **critic** (subagent): Argue against the user's claim.

Example: `Agent({ "subagent_type": "summarizer", "prompt": "<task>", "description": "<short desc>" })`
```

Pi has a single spawn mechanism — the `Agent()` tool. Subagents declared
with `mode="primary"` (which opencode invokes via the bundled
`opencode_manager.py` bash script) are also listed under `Agent()` in the
pi output; there is no bash invocation path.

## Running Compiled Pi Agents

After compilation, run agents with pi:

```bash
cd build
pi run --agent orchestrator "Summarize and critique this claim: ..."
```

Or spawn subagents directly:

```bash
pi run --agent summarizer "Summarize this text: ..."
pi run --agent critic "Critique this claim: ..."
```

## Dual Compilation

The same agent definitions can be compiled for both OpenCode and Pi:

```python
# Compile for OpenCode
opencode_script = CompileScript(
    target=Path("./build_opencode"),
    factory=registry,
    config="prod",
    dialect="opencode",
)
opencode_script.run()

# Compile for Pi
pi_script = CompileScript(
    target=Path("./build_pi"),
    factory=registry,
    config="prod",
    dialect="pi",
)
pi_script.run()
```

See `examples/80_pi_agents/build_both.py` for a complete example.

## Differences from OpenCode Dialect

| Feature | OpenCode | Pi |
|---------|----------|----|
| Output directory | `.opencode/agents/` | `.pi/agents/` |
| Frontmatter format | OpenCode-specific | Pi-subagents YAML |
| Subagent spawning | Task tool | `Agent()` tool |
| Todo tracking | `todoread`/`todowrite` tools | `TODO.md` file conventions (strict/lazy) |
| Permissions | `permission:` block | `tools:` allowlist + `disallowed_tools:` |
| MCP servers | `permission.mcp.<name>` | Not mapped (compile warning; configure `ext:mcp/<tool>` manually) |
| Primary-mode subagents | bash via `opencode_manager.py` | `Agent()` tool (single spawn mechanism) |
| Dual compile | Primary + subagent modes | `also_compile_as_primary` emits a `-primary.md` twin |
| Tool scripts | `scripts/` + bundled infra scripts | `scripts/` (per-tool only, no bundled infra) |

## Limitations

- Pi agents are always standalone; subagent spawning happens at runtime
  via the `Agent()` tool. `also_compile_as_primary` still emits a
  `-primary.md` twin for direct CLI invocation.
- Pi has no `todoread`/`todowrite` tools — todo tracking compiles to
  `TODO.md` file conventions (see `todo_mode` above).
- MCP servers are **not mapped**: an agent declaring `mcp_servers` compiles
  with a `UserWarning` telling you to configure them manually as pi
  extension tools (`ext:mcp/<tool>`). The `tool_permissions.mcp` toggle has
  no pi-side effect.
- JSON-format custom tools get no `custom_tools` frontmatter (pi has no
  equivalent); they are documented in the body as bash-invocable and their
  `tool_scripts` are written to `scripts/` in the build tree.
- `workspace` renders as a prompt instruction only — there is no
  `workspace_io.py`-style enforcement script for pi.

## Future Enhancements

Potential additions:
- Support for `max_turns` in the agent model
- Support for `memory` scope in the agent model
- MCP server → extension tool mapping
- Pi-specific workflow features (e.g., pi's native todo integration)

## See Also

- [Pi Agent Compiler](https://github.com/DehydratedWater/OpenAgentCompiler/blob/main/open_agent_compiler/compiler/dialects/pi_agent/compiler.py)
- [Pi Agent Compile Agent](https://github.com/DehydratedWater/OpenAgentCompiler/blob/main/open_agent_compiler/compiler/dialects/pi_agent/compile_agent.py)
- [Tool Mapping](https://github.com/DehydratedWater/OpenAgentCompiler/blob/main/open_agent_compiler/compiler/dialects/pi_agent/tool_mapping.py)
- [Workflow Renderer](https://github.com/DehydratedWater/OpenAgentCompiler/blob/main/open_agent_compiler/compiler/dialects/pi_agent/workflow_renderer.py)
- [Pi Subagents Extension](https://pi.dev/packages/@tintinweb/pi-subagents)
- [Pi Agent Example](https://github.com/DehydratedWater/OpenAgentCompiler/tree/main/examples/80_pi_agents/)
