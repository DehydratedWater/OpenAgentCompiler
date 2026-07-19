# Tutorial: one agent, three models

*Mini-project for: `ModelPreset`, `VariantSpec`, and `SplitProfile`.*

## The problem

You wrote one good summarizer prompt — but which model should run it?
The strong cloud model is best, the cheaper one is fine for bulk work,
and the local vLLM box is free once it's racked. Maintaining three
copies of the agent is how definitions drift apart. Instead, define the
agent once and let the compiler fan it out into three side-by-side
variants you can invoke — and benchmark — interchangeably.

## What you'll build

A single summarizer `AgentDefinition` compiled in one pass into three
opencode artifacts:

| Artifact | Provider | Model |
|---|---|---|
| `primary.md` | `zai-coding-plan` | `glm-4.5-air` (cheap cloud) |
| `primary-glm51.md` | `zai-coding-plan` | `glm-5.1` (strong cloud) |
| `primary-qwen.md` | `local-vllm-remote` | `qwen35-27b` (local vLLM) |

Prerequisites: [installation](../getting-started/installation.md), the
`opencode` CLI, and for the local variant an OpenAI-compatible endpoint
(e.g. vLLM at `http://localhost:8000/v1`). This tutorial is adapted
from `examples/10_multi_provider`.

## Step 1 — define the agent once

`agents.py`:

```python
from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    ModelPreset,
    SamplingDefaults,
    TemplateSlot,
    TemplateTree,
    VariantSpec,
)


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    summariser = AgentDefinition(
        header=AgentHeader(
            agent_id="multi-summariser",
            name="multi-summariser",
            description="Summarises arbitrary user-supplied text in one paragraph.",
        ),
        usage_explanation_long=(
            "Reads whatever the user sends and returns a single dense"
            " paragraph capturing the key points. No bullet lists, no"
            " preamble — just the summary."
        ),
        usage_explanation_short="one-paragraph summary",
        system_prompt=(
            "You are a concise summariser. Read the user's message and"
            " reply with exactly one paragraph (3-5 sentences) capturing"
            " the key points. Do NOT use bullet lists, do NOT add"
            " preamble. Start the summary directly."
        ),
    )

    agent_id = reg.register_agent(
        "multi-summariser", summariser,
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.5),
    )
    reg.register_template(TemplateTree(
        name="summariser-tpl",
        slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="summariser-tpl"),
    )
    return reg
```

## Step 2 — describe the three models as VariantSpecs

A `ModelPreset` is the full per-model descriptor (provider, model id,
sampling defaults); a `VariantSpec` binds one preset to a compile pass
and a filename postfix:

```python
VARIANTS: list[VariantSpec] = [
    VariantSpec(
        name="default", postfix="",
        preset=ModelPreset(
            name="zai-glm-45-air",
            provider="zai-coding-plan", model_id="glm-4.5-air",
            sampling=SamplingDefaults(temperature=0.5),
        ),
    ),
    VariantSpec(
        name="glm51", postfix="-glm51",
        preset=ModelPreset(
            name="zai-glm-51",
            provider="zai-coding-plan", model_id="glm-5.1",
            sampling=SamplingDefaults(temperature=0.5),
        ),
    ),
    VariantSpec(
        name="qwen", postfix="-qwen",
        preset=ModelPreset(
            name="vllm-qwen35-27b",
            provider="local-vllm-remote", model_id="qwen35-27b",
            sampling=SamplingDefaults(temperature=0.6),
        ),
    ),
]
```

The `local-vllm-remote` provider must exist in your
`~/.config/opencode/opencode.json` as an OpenAI-compatible provider
whose base URL points at your endpoint, e.g.
`http://localhost:8000/v1`. The framework's artifact is correct either
way — if the endpoint is down, opencode reports a connection error at
invocation time, not compile time.

## Step 3 — compile all three in one pass

`build_agents.py`:

```python
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agents import VARIANTS, registry
from open_agent_compiler.compiler.script import CompileScript


def main() -> None:
    script = CompileScript(
        target=HERE / "build",
        factory=registry,
        config="prod",
        variants=VARIANTS,
        clean=True,
        verbose=True,
    )
    result = script.run()
    print(f"wrote {len(result.written_files)} file(s); variants: {result.variants}")
    for path in sorted(result.written_files):
        print(f"  - {path.relative_to(result.target.parent)}")


if __name__ == "__main__":
    main()
```

## Run it

```bash
uv run python build_agents.py
cd build

TEXT="Summarise: Vector databases trade exact search for speed..."
opencode run --agent primary "$TEXT"
opencode run --agent primary-glm51 "$TEXT"
opencode run --agent primary-qwen "$TEXT"
```

The compile prints the three artifacts:

```
wrote 3 file(s); variants: ['default', 'glm51', 'qwen']
  - build/.opencode/agents/primary.md
  - build/.opencode/agents/primary-glm51.md
  - build/.opencode/agents/primary-qwen.md
```

Each file's frontmatter carries its own `model:` line
(`zai-coding-plan/glm-4.5-air`, `zai-coding-plan/glm-5.1`,
`local-vllm-remote/qwen35-27b` — the preset's `qualified_model_name`).
Run the same text through all three and compare: the glm-5.1 summary is
usually the tightest, glm-4.5-air is close for a fraction of the cost,
and the local qwen variant costs nothing per token. You now have an
instant A/B/C harness for "is the cheap model good enough here?"

## Bonus — routing by model class with SplitProfile

`VariantSpec` applies one preset to *every* agent in a pass. In a
larger tree you usually want "small agents on the fast model, deep
agents on the strong one" — that is `SplitProfile`, a `VariantSpec`
whose preset is chosen per agent from its declared `model_class`:

```python
from open_agent_compiler import SplitProfile

split = SplitProfile(
    name="prod-split", postfix="-split",
    class_map={
        "fast": VARIANTS[0].preset,        # glm-4.5-air
        "analytical": VARIANTS[1].preset,  # glm-5.1
    },
    preset=VARIANTS[1].preset,             # fallback
    default_class="analytical",
)
```

An agent opts in at definition time with
`AgentDefinition(..., model_class="fast")`; agents in
`passthrough_classes` (by default `("vision",)`) keep their original
model untouched.

## Why it works

The agent definition never learns which model it runs on — provider
choice lives entirely in `ModelPreset`s applied at compile time. That
one inversion is what makes model comparison, cost tiering, and cloud →
local migration a compile-flag change instead of a refactor, and it is
the same mechanism the improvement loop uses to tune prompts *per
model* rather than settling on one compromise prompt.

## Going further

- `examples/25_per_model_optimization` — the same split, driven through
  the improvement loop so each model class evolves its own winning
  prompt.
- [Variants and profiles guide](../guides/variants-and-profiles.md)
- [Execution tiers](../concepts/execution-tiers.md) — the same presets
  also feed the in-process interactive tier.
