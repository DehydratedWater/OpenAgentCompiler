# open-agent-compiler

Composable agent-tree compiler for [OpenCode](https://opencode.ai),
[Claude Code](https://claude.com/claude-code), and
[Pi](https://pi.dev) (via [@tintinweb/pi-subagents](https://pi.dev/packages/@tintinweb/pi-subagents)).
Define agents once as typed Python, compile them to any supported
runtime, test them with mocks, and improve them with closed-loop
optimization.

- **PyPI**: [`open-agent-compiler`](https://pypi.org/project/open-agent-compiler/)
- **Docs**: <https://dehydratedwater.github.io/OpenAgentCompiler/>

## What it does

Define an agent once in Python:

```python
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry,
    CompilationConfig, ModelParameters,
    TemplateSlot, TemplateTree,
)

def registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="hello", name="hello",
                           description="Friendly greeter."),
        usage_explanation_long="A minimal greeting agent.",
        usage_explanation_short="greets",
        system_prompt="You are a friendly greeter. Reply in one sentence.",
    )
    aid = reg.register_agent("hello", agent,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.7))
    reg.register_template(TemplateTree(name="t",
        slots=[TemplateSlot(name="primary", default_agent_id=aid)]))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="t"))
    return reg
```

Compile it into an opencode-loadable tree:

```bash
uv run oac compile myproj.agents:registry --config prod --target build
```

Run with OpenCode:

```bash
cd build && opencode run --agent primary "Hi"
> primary · glm-4.5-air
Hello there! Nice to meet you.
```

Or compile for Pi (requires the `@tintinweb/pi-subagents` extension for
subagent spawning plus `pi-permission-system` for permission enforcement):

```bash
uv run oac compile myproj.agents:registry --config prod --target build --dialect pi
cd build && pi run --agent primary "Hi"
```

## Key features

- **Pydantic-modeled** agent/tool/skill/workflow definitions — no YAML
  hand-editing, types catch errors at registration time.
- **Multi-variant compilation** — same agent compiled side-by-side
  against different providers/models via `VariantSpec`. `SplitProfile`
  picks per-agent presets by declared `model_class`.
- **Dual tool format** — bash command allowlist or OpenCode-style
  JSON-schema custom_tool, per-agent or per-tool.
- **Built-in test framework** — `CapabilityTest` (introspection),
  `ToolTest` (mocked or real handler), `AgentTest` (end-to-end). 9
  evaluator kinds. JSONL artifacts. Incremental skip via composite hash.
- **Bundled infrastructure scripts** — `subagent_todo.py`,
  `workspace_io.py`, `opencode_manager.py` auto-included when the
  compiled tree references them.
- **Iterative improvement loop** — `oac improve` mutates prompts/tools/
  resources, evaluates candidates against your `OptimisationCriterion`,
  promotes winners.
- **Project scaffolder** — `oac init` generates a Docker-compose'd
  project with FastAPI + cron + optional Postgres / Redis / Qdrant /
  Ollama / Langfuse. Cron POSTs JSON events to the FastAPI server which
  invokes the compiled agents.
- **Multi-dialect** — OpenCode (default) + Claude Code + Pi (via
  [@tintinweb/pi-subagents](https://pi.dev/packages/@tintinweb/pi-subagents)
  and [pi-permission-system](https://github.com/MasuRii/pi-permission-system)),
  with a plug-in `Dialect` protocol for future runtimes.
- **Developer skill bundles** — `oac sync-skills` deploys opinionated
  markdown skill files into a project's `.opencode/skills/` and
  `.claude/skills/` so coding agents working in the repo know how to
  use the framework.

## Install

```bash
pip install open-agent-compiler
# or
uv add open-agent-compiler
```

For development on the framework itself:

```bash
git clone https://github.com/DehydratedWater/OpenAgentCompiler
cd OpenAgentCompiler
uv sync
uv run oac --help
```

## CLI

```
oac init <dir> --template web --llm anthropic …      # scaffold a new project
oac compile <factory> --config prod --target build   # compile agents
oac test <factory> --config prod                     # run embedded tests
oac improve <factory> --target X --criteria c.yaml   # iterative improvement
oac promote improved/X/LATEST.json                   # re-introduce a winner
oac sync-skills <project> --skills opencode,claude   # deploy dev skills
oac info <factory>                                   # introspect registry
```

## Examples gallery

| Example | Demonstrates |
|---|---|
| `examples/00_hello/` | minimum working agent end-to-end with z.ai glm-4.5-air |
| `examples/10_multi_provider/` | one agent compiled three ways: z.ai glm-4.5-air + glm-5.1 + local vLLM Qwen3.5-27B |
| `examples/20_optimization_run/` | weak agent improved via `oac improve` with glm-5.1 as the optimiser |
| `examples/80_pi_agents/` | orchestrator + subagents compiled for Pi runtime with pi-subagents |

All examples are tested end-to-end against real LLMs (see
`examples/README.md`).

## Documentation

**Start with the [Developer Guide](docs/dev-guide.md)** — the complete
walkthrough: setup, core concepts, all three dialects, the worker vs
interactive tier split, tools, workflows, variants, testing, the
improvement loop, CLI reference, and a full examples index. Dialect
deep-dive: [pi-agent-dialect.md](docs/dialects/pi.md).

## Documentation: developer skills

The framework ships 14 skill bundles you can deploy into any project
with `oac sync-skills` (highlights below; `oac sync-skills --help` for
the full set):

- `getting-started` — three commands you'll use most, agent shape
- `authoring-agents` — workflow vs system_prompt, modes, todo_mode
- `authoring-tools` — ScriptTool, MockableTool, AccessProfile
- `writing-tests` — CapabilityTest / ToolTest / AgentTest + evaluators
- `providers-and-models` — ModelPreset, per-agent model assignment
- `variants-and-profiles` — VariantSpec / SplitProfile / CompilationContext
- `docker-and-compose` — the scaffolded Docker setup + failure modes
- `improvement-loop` — `oac improve` + `oac promote`

```bash
uv run oac sync-skills ./myproject --skills opencode,claude
```

After this, coding agents (OpenCode or Claude Code) working in your
project read the skill files and know how to add agents, write tests,
debug Docker, configure providers, etc.

## Project layout

```
open_agent_compiler/
  __init__.py                # Public API re-exports
  cli/                       # `oac` CLI subcommands
  compiler/                  # The compile pipeline + dialect registry
    dialects/{opencode,claude_code,pi_agent}/
  improvement/               # Phase 6 iterative loop
    mutators/                # Mutator implementations
  model/                     # Pydantic models (agents/tools/skills/tests/…)
  runtime.py                 # ScriptTool base class
  scaffold/                  # `oac init` template engine
    files/                   # File generators (Dockerfile, compose, app, …)
  scripts/                   # Bundled handler scripts (auto-copied)
  skills/                    # Developer skill bundles
  testing/                   # Test runner + evaluators + artifacts
tests/                       # pytest tree (mirrors open_agent_compiler/)
examples/                    # Working end-to-end examples
```

## Status

Through Phase 36 (~36 numbered phases shipped). Headline features:

- **Composable agent trees** with `register_with_improvements`
  auto-merging promoted snapshots (Phase 10).
- **Multi-turn `AgentTest`** + sequenced / stateful `MockResponse`
  for streaming/monitoring scenarios (Phase 11).
- **Per-agent MCP allowlists** + bundled MCP-server scaffold via
  `--with-mcp-server` (Phases 12 + 24).
- **Tool-targeted mutators** (description, rules, bash-vs-json
  format) + `tool_failure_rate` criterion (Phase 13).
- **`ScriptTool.execute(input, resources)`** + `ResourceHandle`
  for clean DB / API bindings (Phase 15).
- **Composable context blocks** + `PromptAssembler` with
  volatility-aware ordering (Phase 19).
- **`TaskHandle`** + `SpawnAgentTool` for long-running and
  agent-spawned-from-tool patterns (Phases 20 + 21).
- **FastAPI dispatcher** with sync / async / fire-and-forget modes,
  variant routing, composable `RetryPolicy` (Phase 23).
- **`oac init --interactive`** + auto `uv sync` (Phase 25).
- **Dual-compile (`also_compile_as_primary`)**: every subagent slot
  can also emit a primary twin reachable directly via
  `opencode run --agent <name>-primary` or via opencode_manager
  dispatch (Phase 31).
- **`OpencodeRunner`** — the recommended sync eval runner with
  auto-retry on empty output + 0-1 score clamping (Phase 36).

19 numbered examples under `examples/`. 11 skills under
`open_agent_compiler/skills/content/` totalling 20+ documented patterns from real
project pain.

## Benchmark / verification

The framework's reproducibility benchmark is a complete spec for
building a real multi-agent media-tracking service (7 agents, 5
tools, Postgres, MCP, FastAPI dispatch) with the framework. Use it
to verify that a fresh agentic-coding instance can one-shot a real
project on top of `open_agent_compiler`. The reference
implementation is verified end-to-end (live search API, live z.ai
agent runs, live autoresearch producing a positive baseline delta).

## License

MIT.
