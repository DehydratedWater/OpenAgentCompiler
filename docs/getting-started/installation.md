# Installation

Here you'll install the `open-agent-compiler` package, the `opencode` runtime it
compiles to by default, and verify both work. Prerequisite: Python 3.12 or newer.

## 1. Install the package

With [uv](https://docs.astral.sh/uv/) (recommended, inside a project):

```bash
uv add open-agent-compiler
```

Or with pip:

```bash
pip install open-agent-compiler
```

The distribution name is `open-agent-compiler`, the import name is
`open_agent_compiler`, and the CLI it installs is `oac`. The core package is
dependency-light (Pydantic, PyYAML, loguru) and requires **Python >= 3.12**.

## 2. Optional: interactive-tier extras

The compiler core never imports an LLM framework. Only install an extra
if you plan to use the in-process interactive tier
(`build_interactive_spec` + a binding for streaming chat), described in
[execution tiers](../concepts/execution-tiers.md):

```bash
uv add "open-agent-compiler[langchain]"     # LangChain binding
uv add "open-agent-compiler[pydantic-ai]"   # PydanticAI binding (alternative)
```

These pull in `langchain-core`/`langchain-openai` or
`pydantic-ai-slim[openai]` respectively.

## 3. Install the opencode CLI

Compiled agents are static files — they need a runtime to execute. The default
dialect targets [opencode](https://opencode.ai), so install its CLI and make
sure it is on your `PATH`:

```bash
npm install -g opencode-ai        # or follow the installer at https://opencode.ai
opencode --version
```

Then authenticate opencode with your model provider (for example
`opencode auth login`, or an API key in your opencode config). The compiler
itself never calls an LLM at compile time, so no credentials are needed until
you actually *run* an agent.

### Where Claude Code, pi, and Codex fit

opencode is one of four built-in output dialects. The same agent tree also
compiles to:

- **`claude`** — a `.claude/` tree runnable with the Claude Code CLI.
- **`pi`** — a `.pi/agents/` tree for the pi coding agent. The pi runtime
  needs **two** extensions installed: `@tintinweb/pi-subagents` (subagent
  spawning via the `Agent()` tool) and `pi-permission-system` (enforces the
  compiled `tools:`/`disallowed_tools:` frontmatter at tool-call time). See
  [the pi dialect page](../dialects/pi.md#runtime-requirements-two-extensions).
- **`codex`** — a `.codex/agents/` tree of TOML custom agents plus an
  `AGENTS.md` index for the OpenAI Codex CLI. No extensions needed —
  subagent spawning and sandboxing are built into Codex. See
  [the codex dialect page](../dialects/codex.md).

You only need those CLIs installed if you compile with `--dialect claude`,
`--dialect pi`, or `--dialect codex`. Nothing about the Python-side definitions changes — see
[the opencode dialect page](../dialects/opencode.md) and the
[first agent tutorial](first-agent.md) for the one-line switch.

## 4. Verify

```bash
oac --version
```

You should see the installed version, e.g.:

```text
oac 1.0.0
```

Then confirm the dialect registry is populated:

```bash
oac info --dialects
```

```text
Dialects (4):
  claude
  codex
  opencode
  pi
```

## Next steps

- Build and run your first agent from scratch: [Your first agent](first-agent.md)
- Or start from a full project skeleton: [Project scaffolding with `oac init`](project-scaffold.md)
- Why the framework compiles instead of wrapping an SDK: [Philosophy](../concepts/philosophy.md)
