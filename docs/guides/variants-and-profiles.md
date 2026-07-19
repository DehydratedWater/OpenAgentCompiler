# Variants and profiles: multi-model fleets

In this guide you'll compile one agent tree for several models side by side
with `VariantSpec`, route different agents in the same tree to different
models with `SplitProfile`, branch factories per pass with
`CompilationContext`, and run a per-model optimization loop — because
different models genuinely need different prompts.

## 1. Describe models with ModelPreset

`ModelPreset` is the full per-model descriptor (provider routing, sampling,
limits, reasoning flags); the older `ModelParameters` is just model name +
temperature. Presets are what variants apply:

```python
from open_agent_compiler import ModelLimits, ModelPreset, SamplingDefaults

deep_preset = ModelPreset(
    name="zai-glm-51",                # registry/routing key
    provider="zai-coding-plan",       # emitted as provider/model_id
    model_id="glm-5.1",
    sampling=SamplingDefaults(temperature=0.5),
    limits=ModelLimits(context=128_000),
)
```

`preset.qualified_model_name` yields the provider-qualified string the
runtime frontmatter needs (`zai-coding-plan/glm-5.1`) — a bare model id fails
at runtime, so always keep provider set. You can also register agents
directly under a preset with `reg.register_agent_with_preset(...)`.

## 2. Compile the same agent per model: VariantSpec

Each `VariantSpec` is one pass over the same tree with a different preset and
file postfix. From `examples/10_multi_provider/`:

```python
from open_agent_compiler import VariantSpec
from open_agent_compiler.compiler.script import CompileScript

VARIANTS = [
    VariantSpec(name="default", postfix="",
                preset=ModelPreset(name="zai-glm-45-air",
                                   provider="zai-coding-plan",
                                   model_id="glm-4.5-air",
                                   sampling=SamplingDefaults(temperature=0.5))),
    VariantSpec(name="glm51", postfix="-glm51", preset=deep_preset),
    VariantSpec(name="qwen", postfix="-qwen",
                preset=ModelPreset(name="vllm-qwen35-27b",
                                   provider="local-vllm-remote",
                                   model_id="qwen35-27b",
                                   sampling=SamplingDefaults(temperature=0.6))),
]

CompileScript(target=Path("build"), factory=registry, config="prod",
              variants=VARIANTS, clean=True).run()
```

You get `primary.md`, `primary-glm51.md`, and `primary-qwen.md` side by side
under `build/.opencode/agents/`; pick one at invocation time with
`opencode run --agent primary-glm51`. The compiler rejects two variants
sharing a postfix (they'd silently overwrite each other), and
`clean_strategy` controls wiping: `"full"` (default with `clean=True`),
`"per_variant"` (remove only files matching that variant's postfix — handy
when iterating on one variant), or `"none"`.

## 3. Route models inside one pass: SplitProfile

A `SplitProfile` is a `VariantSpec` whose preset depends on each agent's
declared `model_class` — so one pass fans a tree across co-located models
(cheap local model for quick acks, frontier model for reasoning):

```python
from open_agent_compiler import SplitProfile

split = SplitProfile(
    name="split", postfix="-split",
    preset=deep_preset,                      # fallback
    class_map={"fast": fast_preset,
               "analytical": deep_preset},
    default_class="analytical",
)
CompileScript(target=Path("build"), factory=registry, config="prod",
              variants=[split]).run()
```

Agents opt in once at definition time:

```python
acker = AgentDefinition(..., model_class="fast")
analyzer = AgentDefinition(..., model_class="analytical")
```

Resolution order in `preset_for()`: the agent's class in `class_map`, else
`default_class`'s entry, else the profile's own `preset`.

**The "keep original" rule.** `passthrough_classes` (default `("vision",)`)
lists classes the split does *not* touch — `applies_to()` returns False and
the agent keeps its originally-registered model. This carries over the
resolve()->None semantic from earlier production split-profile
implementations: an image/video agent must not be rerouted onto a text-only
model just because a split profile was applied. Set `passthrough_classes=()`
to split every class.

## 4. Branch factories per pass: CompilationContext

When a factory must decide *at compile time* which tools or skills to include
for the current variant, read the ambient context instead of globals:

```python
from open_agent_compiler.model.core.compilation_context import current_context

def my_agent_factory():
    ctx = current_context()
    if ctx.flag("is_local"):
        tools = [local_only_tool(), shared_tool()]
    else:
        tools = [shared_tool()]
    ...
```

`CompileScript` pushes a frozen `CompilationContext` per variant pass
(carrying `variant_name`, `variant_postfix`, `access_profile_name`,
`mock_profile_name`, `client_id`, and the spec's `feature_flags`); set flags
on the spec with `VariantSpec(..., feature_flags={"is_local": True})`.
Outside a pass, `current_context()` returns an empty context, so factories
still work from tests and REPLs.

## 5. Optimize per model — different models need different prompts

One prompt rarely wins on every model: a small model tends to want tight,
imperative wording, while a larger analytical model exploits richer framing —
and in production fleets one model needed extra hardening where another
needed tighter phrasing. The per-model improvement loop discovers this
empirically. `examples/25_per_model_optimization/` runs one loop per
SplitProfile class:

```python
from open_agent_compiler.improvement import (
    IdentityMutator, LLMPromptRewriter, MutationContext,
    PromptPrefixMutator, run_per_class_loops,
)

results = run_per_class_loops(
    baseline=baseline,               # ComponentVersion of the agent
    mutators=[IdentityMutator(), PromptPrefixMutator("..."),
              LLMPromptRewriter(guidance="...")],
    criterion=CRITERION,             # OptimisationCriterion
    evaluator=evaluator,             # invokes candidates on the class's model
    split_profile=SPLIT_PROFILE,
    max_rounds=2, frontier_size=2,
    output=Path("improved"),
    mutation_context=MutationContext(llm=optimiser_client),
)
```

The evaluator reads each candidate's `model_class` and scores it against the
matching model; one strong optimiser model proposes rewrites for all classes.
Winning snapshots land under `improved/<component>/<class>/<hash>.json`, so
you promote the right prompt per model with `oac promote` and each class
ships its own tuned prompt. See [the improvement loop](improvement-loop.md)
for mutators, criteria, and promotion mechanics.

## Related pages

- [Agent model concepts](../concepts/agent-model.md)
- [Execution tiers](../concepts/execution-tiers.md)
- [Improvement loop](improvement-loop.md)
- [Testing](testing.md)
- [CLI reference](../reference/cli.md)
