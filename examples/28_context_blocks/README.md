# 28 context-blocks — composable prompt assembly with volatility tiers

Demonstrates Phase 19's `ContextBlock` + `PromptAssembler`.

The agent's system prompt is built from named blocks, each tagged with
how often its content changes between invocations. The assembler
auto-sorts blocks by volatility so:

1. The resulting prompt **structure** is legible (immutable persona +
   rules → stable skill docs → fluid user profile → volatile live data).
2. As a happy side effect, the prefix is cache-friendly: providers
   like Anthropic cache the prefix, so when only the volatile tail
   changes the cached prefix is re-used.

## Run it

```bash
uv run python examples/28_context_blocks/build_prompt.py
```

You'll see the composed prompt for two different users, plus a check
that the cacheable prefix stays identical across turns when only the
volatile block changes.

## The volatility tiers

| Tier | Example |
|---|---|
| `immutable` | Persona, security rules — never change. |
| `stable` | Skill docs, tool catalogues — change on deploys. |
| `fluid` | User profile, timezone — change per session. |
| `volatile` | Chat history, live observations — change every turn. |

## Monitoring volatility in production

When the FastAPI scaffold is enabled (`oac init --template=full
--with-postgres`), each block's rendered content is hashed and stored
in the `context_block_versions` table. `GET /metrics/context-volatility`
returns declared-vs-observed change rate per block — flag blocks
declared `stable` that change every run, or `volatile` blocks that
never change.

See the `prompt-structure` skill for the full pattern doc.
