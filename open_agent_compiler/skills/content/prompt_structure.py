"""prompt-structure skill — composable context blocks + volatility ordering."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Composable context blocks — prompt structure with volatility ordering

Real agents need more than a single static `system_prompt`. The chat
agents in the largest production deployments build
their prompt from many *prepended* named pieces — persona, security
rules, user profile, recent observations, chat history. Each piece
has a different rate of change. The framework gives you primitives
to compose these explicitly so:

1. The prompt structure is **legible** — anyone reading it can see
   what each piece is for and in what order it appears.
2. The compose function is **deterministic** — same inputs → same
   output, every call.
3. The volatility tagging is **monitored** — a long-running
   deployment learns whether your declared volatility tier matches
   what each block actually does, and surfaces the mismatch.

The structural ordering also happens to be prefill-cache-friendly:
stable content goes to the front of the prompt → the provider's
prefix cache hits on it → token cost drops. But that's a side
effect. The point is the structure.

## The volatility tiers

| Tier | When to use | Examples |
|---|---|---|
| `immutable` | Never changes session-to-session. | Persona, core rules, security policy. |
| `stable` | Changes rarely (deploys, content edits). | Skill instructions, tool docs. |
| `fluid` | Changes per session / per user. | User profile, time-of-day, locale. |
| `volatile` | Changes per turn. | Chat history, live observations, current ticket. |

`PromptAssembler` sorts blocks by this rank (immutable first,
volatile last). Stable ordering within a tier preserves your
declared order — group your two stable tool-doc blocks however you
want them.

## Composing a prompt from blocks

```python
from open_agent_compiler import ContextBlock, PromptAssembler

persona = ContextBlock(
    name="persona", volatility="immutable",
    content="You are Nova — a thorough research assistant…",
)
security = ContextBlock(
    name="security", volatility="immutable",
    content="Never write outside the workspace. Never run sudo.",
)
skills_block = ContextBlock(
    name="skills-toc", volatility="stable",
    content="Available skills: chat-history, context-cache, …",
)
user_profile = ContextBlock(
    name="user-profile", volatility="fluid",
    content=lambda ctx: f"User: {ctx['name']} (tz={ctx['tz']})",
)
observations = ContextBlock(
    name="live-observations", volatility="volatile",
    content=lambda ctx: ctx["recent_obs"],
)

assembler = PromptAssembler(blocks=[
    persona, security, skills_block, user_profile, observations,
])

system_prompt = assembler.compose(input_context={
    "name": "Alice", "tz": "UTC+1",
    "recent_obs": "<timestamped live data>",
})
```

The composed output is exactly:

```
You are Nova — a thorough research assistant…

Never write outside the workspace. Never run sudo.

Available skills: chat-history, context-cache, …

User: Alice (tz=UTC+1)

<timestamped live data>
```

## Plugging into AgentDefinition

The simplest pattern: build the prompt once at registry construction
and pass the result as `system_prompt`:

```python
AgentDefinition(
    header=AgentHeader(agent_id="chat", name="chat", description=...),
    usage_explanation_long="…", usage_explanation_short="…",
    system_prompt=assembler.compose(input_context=session_ctx),
    …,
)
```

For per-session prompts, build the assembler once at boot and call
`.compose(input_context=…)` inside your runtime layer (e.g., the
FastAPI route handler) right before invoking opencode.

## Explicit position overrides

The auto-sort produces the right structure 95% of the time. For the
remaining 5%, set `position`:

```python
# Pin a "current task" block to the very top regardless of tier.
ContextBlock(
    name="current-task", volatility="volatile",
    content=lambda ctx: ctx["task"],
    position=0,
)
```

position=0 wins over volatility rank; ties between explicit positions
fall back to volatility rank, then registration order.

## Cache breakpoints

By default `assembler.cacheable_prefix()` returns everything up to
(but not including) the first `volatile`-tier block. Set
`cache_breakpoint=True` on an earlier block to pin a closer
boundary:

```python
ContextBlock(
    name="security", volatility="immutable",
    content="…", cache_breakpoint=True,
)
# Subsequent blocks (even stable / fluid ones) are NOT cached.
```

Use this when a downstream block depends on a header that's already
near-cache-line size — splitting at the security block lets the
provider drop the now-irrelevant tail without invalidating the
header cache.

## Volatility is monitored

When the FastAPI scaffold is on with postgres (`oac init --template=full
--with-postgres`), every run hashes each block's rendered content
and writes a row to `context_block_versions`. Operators read
`/metrics/context-volatility` to see:

| block_name | declared | total_runs | distinct_hashes | change_rate |
|---|---|---|---|---|
| persona | immutable | 1024 | 1 | 0.001 |
| skills-toc | stable | 1024 | 1 | 0.001 |
| user-profile | fluid | 1024 | 38 | 0.037 |
| live-observations | volatile | 1024 | 1024 | 1.0 |
| current-mood | stable | 1024 | 1024 | **1.0** ← mistagged |

The last row is signal: it's declared `stable` but changes every
run. Retag it to `volatile` (or split it into a stable part + a
volatile part) so the prompt structure honestly reflects what the
data does. The metric feeds the same operator dashboards as
`/metrics/tool-failures` — same monitoring substrate, two
dimensions.

## Anti-patterns

- **Lumping immutable + fluid into one block.** A "persona + recent
  mood" combined block invalidates the entire prefix every turn. Split
  them.
- **Using lambdas that close over session-mutable state.** The block
  must be deterministic given `input_context`. If your lambda reads
  a module-level dict that other code mutates, repeated `compose()`
  calls produce drift — the monitoring layer catches it but the
  fix is to thread the data through `input_context` properly.
- **Tagging optimistically without checking the metric.** "I think
  this is stable" is a hypothesis; the `change_rate` column tells
  you whether it actually is. Re-tag based on what you observe,
  not what you wish.

## See also

- `authoring-agents` — how to declare an AgentDefinition.
- `improvement-loop` — the autoresearch loop can also optimise
  prompts assembled from blocks; promote the winner back as a new
  immutable block.
- `docker-and-compose` — the FastAPI service that records the
  per-run snapshots.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="prompt-structure",
        description=(
            "Composable context blocks + volatility tiers + prompt"
            " assembly. The structural pattern for real agents — and the"
            " monitored dimension long-running deployments use to keep"
            " volatility tags honest."
        ),
        body_markdown=BODY,
        version="1.0.0",
        tools_hint=(
            "ContextBlock", "PromptAssembler", "Volatility",
            "/metrics/context-volatility",
        ),
    )
