# The Claude Code dialect

Compile the same registry for Claude Code instead of opencode:

```bash
uv run oac compile agents:registry --config prod --target build --dialect claude
```

or `CompileScript(..., dialect="claude")`.

## How it works

`ClaudeCodeCompiler` subclasses `OpenCodeCompiler`
(`open_agent_compiler/compiler/dialects/claude_code/compiler.py`): it
runs the full opencode compile, then moves the resulting `.opencode/`
tree to `.claude/`. The bundled-scripts copy is path-independent, so
tool scripts land in the same top-level `scripts/` directory either way:

```
build/
  .claude/agents/<slot><postfix>.md   # same files, relocated
  scripts/
```

Everything on the [opencode dialect page](opencode.md) — frontmatter
shape, permission mapping, primary/subagent modes, dual-compile twins,
the `{name: bool}` tools map — applies verbatim to the emitted files.

## Differences and limitations

- **Output location only.** The dialect changes where files land, not
  what they contain. Agent files keep the opencode frontmatter schema
  (`mode:`, `permission:`, `tool:`, `custom_tools:`); Claude Code reads
  the fields it knows (`description`, `model`) from
  `.claude/agents/*.md` and ignores the rest, so runtime enforcement of
  the compiled `permission:` block depends on your Claude Code
  version/settings. The generated `SECURITY POLICY` prompt section
  still communicates the policy to the agent either way.
- **Primary dispatch is opencode-specific.** `opencode_manager.py` and
  `opencode run --agent <name>-primary` don't apply; in Claude Code,
  subagents are invoked via its own Task/agent mechanism.
- **No `opencode.json`** — provider and MCP configuration follows Claude
  Code's own settings files instead.

Treat this dialect as a convenience for teams running the same fleet
definitions inside Claude Code; for full permission-enforcement parity,
run the opencode dialect. For the third bundled target see
[pi](pi.md), and `oac info --dialects` lists everything registered
([CLI reference](../reference/cli.md)).
