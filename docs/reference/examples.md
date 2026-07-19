# Examples index

Every directory under `examples/` is a self-contained, runnable demonstration
of one framework capability, ordered by number from "hello world" to full SaaS
scaffolds. Run them from the repo root; most compile with a `build_agents.py`
and are invoked with `opencode run` from their `build/` directory (see
`examples/README.md` for prerequisites — several exercise real LLM backends).

```bash
uv run python examples/00_hello/build_agents.py
cd examples/00_hello/build
opencode run --agent primary "Hi, I'm Dana"
```

## Basics

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `00_hello` | The minimum: one agent defined, compiled, and invoked via opencode | [Your first agent](../getting-started/first-agent.md) |
| `10_multi_provider` | One agent compiled as three variants against different providers/models side by side | [Agent model](../concepts/agent-model.md) |

## Improvement loop

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `20_optimization_run` | A deliberately weak agent improved via `oac improve`, with a stronger model as optimizer | [Improvement loop](../guides/improvement-loop.md) |
| `25_per_model_optimization` | Independent winners per model class — separate optimized prompts for fast / analytical / local | [Improvement loop](../guides/improvement-loop.md) |
| `26_promote_and_reload` | Closing the loop: a promoted snapshot merges onto the baseline on the next compile | [Improvement loop](../guides/improvement-loop.md) |
| `27_composable_improvements` | Agent prompt, skill, and tool each independently promoted, all merged at register time | [Improvement loop](../guides/improvement-loop.md) |

## Prompt assembly & long-running work

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `28_context_blocks` | Volatility-tagged `ContextBlock`s + `PromptAssembler` for cache-friendly prompt composition | [Agent model](../concepts/agent-model.md) |
| `29_long_running_task` | The `TaskHandle` return shape for tools that may take minutes | [Tools guide](../guides/tools.md) |

## Tools, resources, MCP, dispatch

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `30_tools` | One ScriptTool compiled in `bash`, `json`, and `both` tool formats — what each puts in the frontmatter | [Tools guide](../guides/tools.md) |
| `31_spawn_agent` | `SpawnAgentTool` — typed agent-to-agent composition through a tool call | [Tools guide](../guides/tools.md) |
| `32_multi_turn_mocks` | Multi-turn `AgentTest` with sequenced `MockResponse`s for monitoring-style scenarios | [Testing guide](../guides/testing.md) |
| `33_sqlite_resources` | ScriptTool `execute(input, resources)` with an `AccessProfile`-bound SQLite database | [Tools guide](../guides/tools.md) |
| `34_mcp_per_agent` | Two agents declaring different MCP server subsets in one compile | [Tools guide](../guides/tools.md) |
| `35_fastapi_dispatch` | FastAPI dispatch: sync / async / fire-and-forget modes, variant routing, retry with fallback chains | [Execution tiers](../concepts/execution-tiers.md) |
| `36_mcp_server` | Compiled agents exposed *as* MCP tools alongside the FastAPI REST API | [Project scaffolding](../getting-started/project-scaffold.md) |

## Multi-agent structure

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `40_subagents` | An orchestrator delegating to two Task-tool subagents | [Agent model](../concepts/agent-model.md) |
| `50_primary_dispatch` | Primary-to-primary spawning via the bundled `opencode_manager.py` bash dispatcher (fresh sessions, not Task) | [Execution tiers](../concepts/execution-tiers.md) |
| `60_workflow_agent` | The full workflow grammar in one agent: numbered steps, criteria, gates, routes, todo tracking | [Agent model](../concepts/agent-model.md) |

## Testing

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `70_oac_test` | `oac test` end to end: capability + tool tests, mock profiles, JSONL artifacts, incremental green-hash skip | [Testing guide](../guides/testing.md) |

## Other runtimes (dialects)

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `80_pi_agents` | The same orchestrator + subagents tree compiled for opencode **and** pi (`build_both.py`) | [Dialects](../dialects/opencode.md) |
| `81_pi_exploration` | Delegating to pi's built-in Explore agent via the `Agent()` tool | [Dialects](../dialects/opencode.md) |
| `85_matrix_live_chat` | **Capstone**: one tree → 2 harnesses × 2 models, per-target autoloops (incl. the interactive tier, LLM-judged), per-target promotion, and one live chat dispatching any compiled variant | [Optimization targets](../guides/optimization-targets.md) |

## Scaffolds

| Example | What it demonstrates | Learn it in |
|---|---|---|
| `90_init_scaffold` | Three `oac init` template shapes (barebones / web / full) generated side by side for browsing | [Project scaffolding](../getting-started/project-scaffold.md) |
| `91_saas_personalized` | The `saas-personalized` template: per-client intake → personalize → serve, pre-wired to per-client auto-optimization | [Project scaffolding](../getting-started/project-scaffold.md) |

`examples/_shared/` holds helpers reused across examples (not a lesson in
itself).

## Suggested path

1. `00_hello` → [first agent](../getting-started/first-agent.md)
2. `30_tools` + `33_sqlite_resources` → [tools](../guides/tools.md)
3. `70_oac_test` + `32_multi_turn_mocks` → [testing](../guides/testing.md)
4. `20`–`27` → [improvement loop](../guides/improvement-loop.md)
5. `40`/`50`/`60` for structure, `80`/`81` when you need a second runtime
6. `90`/`91` when you're ready to [scaffold a real project](../getting-started/project-scaffold.md)
