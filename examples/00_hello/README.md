# 00 hello

The smallest possible working agent: one `AgentDefinition`, one slot,
one z.ai-backed model.

## Build

```bash
uv run python examples/00_hello/build_agents.py
```

Produces `examples/00_hello/build/.opencode/agents/primary.md`.

## Invoke

```bash
cd examples/00_hello/build
opencode run --agent primary "Hi, I'm Dan"
```

Expected: one short greeting from the model (e.g. "Hello, Dan!").

## What's exercised

- `AgentDefinition` + `AgentHeader`
- `register_agent` with `ModelParameters` (provider/model string form)
- `TemplateTree` + `TemplateSlot` (single primary slot)
- `CompilationConfig`
- `CompileScript` with `clean=True` + `verbose=True`
- The end-to-end compile → `.opencode/agents/primary.md` → `opencode run` flow
