"""providers-and-models skill — ModelPreset, multi-provider wiring."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Providers and models

Two layers carry model information:

1. **`ModelParameters`** — the v0.1 minimum (model_name + temperature).
   Use for trivial cases where you don't need sampling/limit overrides.
2. **`ModelPreset`** — the richer descriptor (provider + model_id +
   sampling + limits + reasoning + modalities + provider_options).
   Use for anything beyond a one-line config.

## Registering with a preset

```python
from open_agent_compiler import ModelPreset, SamplingDefaults, ModelLimits

sonnet = ModelPreset(
    name="sonnet-prod",
    provider="anthropic",
    model_id="claude-sonnet-4-5-20250929",
    sampling=SamplingDefaults(temperature=0.7, top_p=0.95),
    limits=ModelLimits(context=200_000, output=32_768),
    reasoning=True,
    interleaved=True,
)

reg.register_agent_with_preset("my-agent", agent_def, sonnet)
```

The discriminator that builds the agent_id uses the preset name (not
the model_id), so registering the same logical agent under two
presets with the same model but different sampling produces distinct
agent_ids. That distinction is what enables Phase 2.1's
multi-variant compilation to address each version individually.

## Per-agent vs per-subagent models

Each agent in the resolved tree carries its own ModelParameters.
Subagents (slot != "primary") can use different models than the
primary by registering them with different presets:

```python
fast = ModelPreset(name="fast", provider="vllm",
                   model_id="qwen35-35b-a3b", ...)
deep = ModelPreset(name="deep", provider="anthropic",
                   model_id="claude-sonnet-4-5", ...)

ack_id = reg.register_agent_with_preset("acker", acker_def, fast)
analyzer_id = reg.register_agent_with_preset("analyzer", analyzer_def, deep)

reg.register_template(TemplateTree(
    name="t",
    slots=[
        TemplateSlot(name="primary", default_agent_id=analyzer_id),
        TemplateSlot(name="ack", default_agent_id=ack_id),
    ],
))
```

The primary uses Claude, the subagent uses Qwen. Compile once, both
get the right model in their frontmatter.

## Adding a new provider

The framework doesn't ship an LLM client — your tools call whatever
SDK you want. The provider's name in `ModelPreset.provider` is purely
informational at compile time (used in the opencode.json provider
block when the OpenCode dialect emits one).

Common providers:

| Provider | provider_options keys | Typical model_id |
|----------|----------------------|------------------|
| `anthropic` | (none, env: `ANTHROPIC_API_KEY`) | `claude-sonnet-4-5-20250929` |
| `openai` | (none, env: `OPENAI_API_KEY`) | `gpt-4o-mini` |
| `openrouter` | `base_url` | `anthropic/claude-sonnet-4.5` |
| `vllm` | `base_url` | `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| `zai-coding-plan` | `base_url`, env: `ZAI_API_KEY` | `glm-4.5-air` |

For an unknown provider, set `provider="other"` and put the
configuration in `provider_options` as opaque key-value pairs. The
compiler treats this dict as pass-through data; the runtime (your
ScriptTools or the OpenCode runtime) interprets it.

## API-key embedding gotcha

OpenCode's CLI does **not** resolve `env:VAR` references inside
`opencode.json`. If you write `"apiKey": "env:ANTHROPIC_API_KEY"` and
hand the file to `opencode run`, you'll get a literal `env:...` string
as the key.

Workaround: read env at compile time, write the resolved key into
opencode.json. See `build_agents.py` in the scaffolded project for
the pattern.

## SplitProfile for model_class routing

When you want different agents in the same compile pass to use
different models based on their declared `model_class` (e.g. "fast"
vs "analytical"), see the `variants-and-profiles` skill.

See also: `variants-and-profiles`, `authoring-agents`.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="providers-and-models",
        description=(
            "ModelPreset vs ModelParameters, per-agent / per-subagent models,"
            " registering new providers, the API-key embedding gotcha."
        ),
        body_markdown=BODY,
        tools_hint=("ModelPreset", "ModelParameters", "register_agent_with_preset"),
    )
