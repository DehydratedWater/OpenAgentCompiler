"""variants-and-profiles skill — multi-variant compilation, SplitProfile."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Variants and profiles

When you need the same logical agent compiled in multiple
configurations side-by-side (different models, different feature
flags, different access bindings), the framework gives you four
primitives. All compose.

## VariantSpec — one preset per pass

```python
from open_agent_compiler import VariantSpec, ModelPreset, SamplingDefaults

specs = [
    VariantSpec(
        name="claude", postfix="-claude",
        preset=ModelPreset(name="c", provider="anthropic",
                           model_id="claude-sonnet-4-5",
                           sampling=SamplingDefaults(temperature=0.7)),
    ),
    VariantSpec(
        name="glm", postfix="-glm",
        preset=ModelPreset(name="g", provider="zai-coding-plan",
                           model_id="glm-4.5-air",
                           sampling=SamplingDefaults(temperature=0.7)),
    ),
]

CompileScript(
    target=Path("build"), factory=registry, config="prod",
    variants=specs,
).run()
```

Produces `build/agent_primary-claude.md` and `build/agent_primary-glm.md`
side-by-side. The runtime picks one at invocation time.

## SplitProfile — preset per model_class

When agents within the same tree should use different models based on
a declared role:

```python
from open_agent_compiler import SplitProfile

class_map = {
    "fast": fast_preset,           # for quick acks
    "analytical": deep_preset,     # for reasoning
}

split = SplitProfile(
    name="qwen35-split", postfix="-split",
    preset=deep_preset,            # fallback
    class_map=class_map,
    default_class="analytical",
)

CompileScript(
    target=Path("build"), factory=registry, config="prod",
    variants=[split],
).run()
```

Agents declare their class on `AgentDefinition.model_class`:

```python
acker = AgentDefinition(..., model_class="fast")
analyzer = AgentDefinition(..., model_class="analytical")
```

The split profile dispatches per agent in one pass.

## CompilationContext — feature flags without globals

When agent factories need to branch at compile time on which variant
they're being built for:

```python
from open_agent_compiler import current_context

def my_agent_factory():
    ctx = current_context()
    if ctx.flag("is_local"):
        tools = [local_only_tool(), shared_tool()]
    else:
        tools = [shared_tool()]
    return AgentBuilder().tools(tools).build()
```

The CompileScript pushes a context per variant pass; factories read it
via `current_context()`. Set `feature_flags` on the VariantSpec:

```python
VariantSpec(
    name="local-build", postfix="-local",
    preset=preset,
    feature_flags={"is_local": True},
)
```

## AccessProfile — symbolic resource routing

(See the `authoring-tools` skill for the full primer.) An
AccessProfile binds tool resource names to concrete adapters. Used
together with mock profiles for tests:

```python
# Compile production
CompileScript(..., access_profile="prod").run()

# Compile a CI variant with mocked external systems
CompileScript(..., access_profile="ci", mock_profile="happy-path").run()
```

The CompilationContext surfaces both names so factories can specialize.

## Multi-variant clean strategy

```python
CompileScript(
    target=Path("build"), factory=registry, config="prod",
    variants=specs,
    clean_strategy="full",  # | "per_variant" | "none"
).run()
```

- `full` — wipe the target before any variant writes. Default when
  `clean=True`.
- `per_variant` — before each variant, remove files matching that
  variant's postfix. Useful when iterating on one variant.
- `none` — touch nothing existing.

CompileScript also validates that no two variants share a postfix —
that would silently overwrite each other's output.

## Build-order graph

The compiler topologically sorts the resolved tree using each agent's
`subagents` field (parents first). This means orchestrators compile
before the agents they delegate to, so if/when stub-overwrite
semantics land in a later phase, the correct order is guaranteed.
You don't need to maintain an `agents-in-this-order` list manually
the way large production deployments once had to.

See also: `providers-and-models`, `authoring-tools`, `writing-tests`.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="variants-and-profiles",
        description=(
            "VariantSpec for side-by-side variants, SplitProfile for"
            " model_class dispatch, CompilationContext for feature flags,"
            " clean strategies + build-order graph."
        ),
        body_markdown=BODY,
        tools_hint=("VariantSpec", "SplitProfile", "CompilationContext",
                    "CompileScript"),
    )
