# OpenAgentCompiler

Python-first agent framework that compiles agent definitions into backend-specific configurations for Claude Code and OpenCode.

## Naming

- **Distribution name** (pip/uv): `agent-framework`
- **Import name** (Python): `open_agent_compiler`
- These differ intentionally — the consumer `fren_infrastructure_control_v3` depends on `agent-framework` and imports `open_agent_compiler`

## Architecture

```
Builder -> AgentDefinition -> Compiler -> backend dict -> Writer -> disk -> Manager -> external process
```

- **Builders** (`open_agent_compiler.builders`): Fluent API classes that produce immutable data types via `.build()`
- **Compiler** (`open_agent_compiler.compiler`): Transforms an `AgentDefinition` into a backend-specific dict (`opencode`)
- **Writers** (`open_agent_compiler.writers`): Sync writers that persist compiled dicts to disk (project files, configs, scripts)
- **Managers** (`open_agent_compiler.managers`): Async lifecycle managers that deploy/invoke/teardown agents against external backends

## Code conventions

- **Python 3.12+** — use modern syntax (`X | Y` unions, StrEnum, slots)
- **Absolute imports** — always use `from open_agent_compiler.x import Y`, never relative imports
- **Frozen dataclasses with slots** for all data types in `_types.py` — immutable and memory-efficient
- **Protocol-based interfaces** in `_base.py` files — implementations explicitly inherit from them
- **Fluent builders** return `self` from setters, validate in `build()`, and support `reset()`
- **Async managers** — all manager methods are `async` since they'll call external processes/HTTP

## Project layout

```
src/open_agent_compiler/       # package root (src-layout)
    _types.py                  # AgentDefinition, AgentConfig, ToolDefinition, ActionDefinition, ToolPermissions, AgentPermissions, ModelProvider, StreamFormat, ParameterDefinition
    compiler.py                # compile_agent()
    runtime.py                 # ScriptTool base class (CLI entry point for handler scripts)
    builders/
        _base.py               # Builder[T] Protocol
        agent.py               # AgentBuilder
        config.py              # ConfigBuilder
        tool.py                # ToolBuilder (from_script, from_handler introspection)
    writers/
        _base.py               # Writer Protocol
        opencode.py            # OpenCodeWriter (filesystem backend)
    managers/
        _base.py               # Manager Protocol
        opencode_server.py     # OpenCodeServerManager (HTTP backend)
tests/
    conftest.py                # shared fixtures
    builders/                  # builder tests
    writers/                   # writer tests
    managers/                  # manager tests
    test_compiler.py           # compiler tests
    test_runtime.py            # ScriptTool runtime tests
```

## Build & test

```bash
uv sync --all-extras      # install with dev + bench deps
uv run pytest tests/ -v   # run all tests
uv run ruff check .       # lint
uv run mypy               # type check (strict mode)
```

## Tooling

- **ruff** — linting (E, F, W, I, UP, B, SIM, RUF rules) and formatting
- **mypy** — strict type checking, configured in pyproject.toml
- **pre-commit** — runs ruff (lint + format), mypy, and basic file checks on every commit
- **Long command strings** — add `# noqa: E501` to lines containing bash commands or usage examples that exceed 88 chars. These are literal command templates that must stay on one line for readability.
- **Bundled scripts** (`scripts/subagent_todo.py`, `scripts/opencode_manager.py`) are copied verbatim from v2 and excluded from ruff/mypy via `pyproject.toml` overrides. Do not lint-fix them.

## XDG_DATA_HOME convention

**CRITICAL:** Any code that runs opencode agents MUST set `XDG_DATA_HOME` to the consumer project's `.opencode/data/` directory. This is the single source of truth for session storage — all contexts (web server, manager, bot, tests) must use the same path so sessions appear in the web UI. **Never use `~/snap/...` or any other path.**

## Permission model

The compiler generates a `permission:` section in each agent's frontmatter that controls what tools the agent can use at runtime. The core mechanism:

1. **`"*": "deny"`** — a single global deny blocks all tools by default (read, edit, bash, skill, task, todoread, todowrite, MCP, doom_loop — everything)
2. **Selective allows** — only tools the agent actually needs get explicit `"allow"` entries
3. **Bash patterns** — bash always gets its own sub-dict with `"*": "deny"` + per-script allows
4. **MCP** — blocked by the global deny. When `auto_mcp_deny=False`, the compiler emits selective allow patterns (`_DEFAULT_MCP_PATTERNS`) to re-enable MCP tools
5. **doom_loop** — only emitted when set to `"allow"` (deny is implicit via `"*": "deny"`)

The `tool:` section is informational only — it controls what tools the model *sees*, but is **not enforced** in `opencode run` mode. All actual enforcement goes through `permission:`.

Example compiled output:
```yaml
permission:
  "*": deny
  read: allow          # only when agent needs it
  bash:
    "*": "deny"
    "uv run scripts/foo.py *": "allow"
  todoread: allow      # only when agent needs it
  todowrite: allow
```

## Consumer project

`fren_infrastructure_control_v3` references this package via:
```toml
[tool.uv.sources]
agent-framework = { path = "../OpenAgentCompiler", editable = true }
```
