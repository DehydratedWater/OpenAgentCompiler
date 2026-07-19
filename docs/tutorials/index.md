# Tutorials

Each tutorial is a mini-project: a small, complete build you can run
end to end, written around one of the repo's tested `examples/`
directories. They are ordered roughly by dependency — later tutorials
assume you can compile a basic tree — but each one stands alone.

| Tutorial | You build | Features it motivates | Read alongside |
|---|---|---|---|
| [Support-ticket triage bot](support-triage-bot.md) | A dispatcher routing tickets to billing/tech specialist subagents | Agent trees, `TemplateSlot`, subagents, Task-tool + primary-mode dispatch | [Agent model](../concepts/agent-model.md), [Workflows and subagents](../guides/workflows-and-subagents.md) |
| [Database reporting agent](database-reporting-tool.md) | A daily-report agent over a resource-bound SQLite tool, tested mock-only in CI | `ScriptTool`, `AccessProfile` resources, `MockResponse`, `ToolTest`/`AgentTest`, `oac test` | [Tools](../guides/tools.md), [Testing](../guides/testing.md) |
| [One agent, three models](one-agent-three-models.md) | The same summarizer compiled for a strong cloud model, a cheap cloud model, and local vLLM | `ModelPreset`, `VariantSpec`, `SplitProfile` | [Variants and profiles](../guides/variants-and-profiles.md), [Registry and compilation](../concepts/registry-and-compilation.md) |
| [Self-improving agent](self-improving-agent.md) | A weak agent measurably improved, promoted, and auto-reloaded | `OptimisationCriterion`, mutators, `IterativeLoop`, `oac promote`, `apply_promoted_to_agent` | [Improvement loop](../guides/improvement-loop.md), [Philosophy](../concepts/philosophy.md) |
| [Fast chat, slow worker](fast-chat-slow-worker.md) | An in-process chat agent dispatching heavy jobs to a compiled worker | Interactive tier, `build_interactive_spec`, `run_interactive`, `SpawnAgentTool`, event sinks | [Execution tiers](../concepts/execution-tiers.md), [Interactive tier](../guides/interactive-tier.md) |

New to the framework entirely? Start with
[installation](../getting-started/installation.md), then do the triage
bot first — it introduces the registry → template → compile flow every
other tutorial builds on. The tested source projects for all five live
under `examples/` in the repository.
