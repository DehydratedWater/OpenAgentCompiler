# Examples gallery

Working end-to-end examples that exercise the framework against real
LLM backends. Each example is self-contained and runnable from the
repo root with `uv run`.

| Example | What it demonstrates | Models used |
|---|---|---|
| `00_hello/` | The minimum: one agent compiled + invoked via opencode | `zai-coding-plan/glm-4.5-air` |
| `10_multi_provider/` | Same agent, three variants (z.ai default, z.ai glm-5.1, local vLLM Qwen) compiled side-by-side | glm-4.5-air, glm-5.1, qwen35-27b |
| `20_optimization_run/` | A deliberately-weak agent improved via `oac improve`; glm-5.1 is the optimizer | glm-4.5-air (target), glm-5.1 (improver) |
| `25_per_model_optimization/` | One agent, independent winners per model class — `run_per_class_loops` produces a separate optimised prompt for fast / analytical / local | glm-4.5-air, glm-5.1, qwen35-27b |
| `26_promote_and_reload/` | The closing of the auto-improve loop: `apply_promoted_to_agent` merges a promoted snapshot onto the baseline on the next compile | glm-4.5-air |
| `27_composable_improvements/` | Self-evolving composable parts: agent prompt + skill + tool each independently promoted, all merged via `register_with_improvements` | glm-4.5-air |
| `28_context_blocks/` | Volatility-tagged ContextBlocks + PromptAssembler — composable prompt assembly with cache-friendly structure (Phase 19) | — |
| `29_long_running_task/` | TaskHandle return shape for tools that may take minutes (Phase 20) | — |
| `31_spawn_agent/` | SpawnAgentTool — typed `[agent 1] → tool → [agent 2]` composition (Phase 21) | — |
| `32_multi_turn_mocks/` | Multi-turn AgentTest + sequenced MockResponse for monitoring scenarios (Phase 11) | — |
| `33_sqlite_resources/` | ScriptTool with `execute(input, resources)` — SQLite-bound notes tool (Phase 15) | — |
| `34_mcp_per_agent/` | Two agents declaring different MCP server subsets in the same compile (Phase 12) | — |
| `35_fastapi_dispatch/` | FastAPI dispatch — sync / async / fire-and-forget modes, variant routing, composable RetryPolicy with fallback_chain (Phase 23) | — |
| `36_mcp_server/` | `--with-mcp-server` exposes compiled agents as MCP tools alongside the FastAPI REST API (Phase 24) | — |
| `40_subagents/`, `50_primary_dispatch/`, `60_workflow_agent/`, `70_oac_test/` | Subagent trees, primary→primary dispatch, workflow agents, embedded testing | glm-4.5-air |
| `80_pi_agents/`, `81_pi_exploration/` | The pi dialect: same tree compiled for opencode **and** pi; delegating to pi's built-in Explore agent | glm-4.5-air |
| `85_matrix_live_chat/` | **Capstone**: one tree → 2 harnesses × 2 models, per-target autoloops (incl. the interactive tier, LLM-judged), per-target promotion, live chat dispatching any compiled variant — fully offline-runnable | — (offline) |
| `90_init_scaffold/`, `91_saas_personalized/` | `oac init` template gallery; the per-client personalization SaaS shape | — |

## Pre-requisites

- the `opencode` CLI installed and on your PATH (install per
  <https://opencode.ai>).
- `.env` at the repo root with `ZAI_API_KEY` (z.ai max coding plan
  works out of the box). Local vLLM examples additionally need a
  reachable `VLLM_BASE_URL`.
- The user's `~/.config/opencode/opencode.json` already declares the
  `zai-coding-plan`, `local-vllm-remote`, and `local-vllm` providers —
  these examples inherit that config.

## Run an example

```bash
# Compile
uv run python examples/00_hello/build_agents.py

# Invoke (from the example's build/ dir so opencode picks up the agents)
cd examples/00_hello/build
opencode run --agent primary "Hi, I'm Dan"
```

The `build/` directory inside each example is gitignored — recompile
freely.
