# 10 multi-provider

Same `AgentDefinition` (a one-paragraph summariser) compiled three
times in one pass, each binding a different provider/model via
`VariantSpec`:

| Slot file | Provider | Model |
|---|---|---|
| `primary.md` | `zai-coding-plan` | `glm-4.5-air` |
| `primary-glm51.md` | `zai-coding-plan` | `glm-5.1` |
| `primary-qwen.md` | `local-vllm-remote` | `qwen35-27b` (Qwen3.5-27B-AWQ-BF16-INT8) |

## Build

```bash
uv run python examples/10_multi_provider/build_agents.py
```

Produces three agent files under
`examples/10_multi_provider/build/.opencode/agents/`.

## Invoke each variant

```bash
cd examples/10_multi_provider/build

opencode run --agent primary "Summarise: …text…"
opencode run --agent primary-glm51 "Summarise: …text…"
opencode run --agent primary-qwen "Summarise: …text…"
```

## What's exercised

- `ModelPreset` + `SamplingDefaults` (rich descriptor with
  `provider` + `model_id` → emitted as `provider/model_id` in the
  YAML frontmatter via `qualified_model_name`).
- `VariantSpec` — postfix-based naming, per-variant preset override.
- `CompileScript(variants=…)` — multi-pass compile to one target.
- Real-world provider matrix: z.ai SaaS + local-vLLM-remote.

## Local vLLM prerequisite

The `primary-qwen` variant requires the local vLLM endpoint
configured in `~/.config/opencode/opencode.json` under provider
`local-vllm-remote` (base URL e.g. `http://localhost:8000/v1`).
If unreachable, opencode reports a connection error; the framework's
artifact remains correct.
