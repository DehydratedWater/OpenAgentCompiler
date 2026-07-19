# Tutorial: a support-ticket triage bot

*Mini-project for: agent trees, `TemplateSlot`s, subagents, and dispatch.*

## The problem

A single "do everything" support agent carries the billing policy, the
debugging checklist, and the routing logic in one prompt — and every
new domain makes it worse at all the others. What you actually want is
a small tree: one dispatcher that reads the ticket and routes it, plus
focused specialists that each carry only their own domain prompt.

## What you'll build

A three-agent tree compiled to opencode artifacts:

- **`triage`** — the primary dispatcher. Reads an incoming ticket,
  decides the category, and delegates via the Task tool.
- **`billing-specialist`** — a subagent that only knows billing.
- **`tech-specialist`** — a subagent that only knows troubleshooting,
  running on a *different* model than the rest of the tree.

Prerequisites: the framework installed
([installation](../getting-started/installation.md)), the `opencode`
CLI, and at least one configured provider. Adapted from
`examples/40_subagents` (closing pointer: `examples/50_primary_dispatch`);
the model strings match those examples — substitute your own freely.

## Step 1 — define the specialists

Create a project directory with an `agents.py`. Each specialist is a
plain `AgentDefinition` with a tight, single-domain system prompt:

```python
"""agents.py — support triage tree."""
from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    AgentToolPermissions,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)


def _billing_specialist() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="billing-specialist",
            name="billing-specialist",
            description="Resolves billing and subscription questions.",
        ),
        usage_explanation_long=(
            "Receives a billing-related ticket from its parent and returns"
            " a short, actionable answer: cause, next step, refund path."
        ),
        usage_explanation_short="billing answers",
        system_prompt=(
            "You are a billing support specialist. Answer the ticket in at"
            " most 4 sentences: likely cause, the customer's next step, and"
            " whether a refund or credit applies. Never answer technical"
            " questions."
        ),
    )


def _tech_specialist() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="tech-specialist",
            name="tech-specialist",
            description="Diagnoses technical problems from ticket text.",
        ),
        usage_explanation_long=(
            "Receives a technical ticket and returns a numbered diagnosis:"
            " most likely cause first, then the checks to run, in order."
        ),
        usage_explanation_short="technical diagnosis",
        system_prompt=(
            "You are a technical support specialist. Reply with a short"
            " numbered list: 1) most likely cause, 2-4) the checks to run"
            " in order. Be concrete; never discuss billing."
        ),
    )
```

## Step 2 — define the dispatcher

The dispatcher references the specialists by `AgentHeader` with
`mode="subagent"` — that wiring lists them under "Available Subagents"
in the compiled prompt and scopes the Task tool to those two targets:

```python
def _triage() -> AgentDefinition:
    billing_ref = AgentHeader(
        agent_id="billing-specialist", name="billing-specialist",
        description="Billing and subscription questions.",
        mode="subagent",
    )
    tech_ref = AgentHeader(
        agent_id="tech-specialist", name="tech-specialist",
        description="Technical problems and outages.",
        mode="subagent",
    )
    return AgentDefinition(
        header=AgentHeader(
            agent_id="triage",
            name="triage",
            description="Routes support tickets to the right specialist.",
        ),
        usage_explanation_long=(
            "Reads an incoming ticket, classifies it as billing or"
            " technical, and delegates via the Task tool. Never answers"
            " inline."
        ),
        usage_explanation_short="ticket router",
        subagents=[billing_ref, tech_ref],
        tool_permissions=AgentToolPermissions(),
        system_prompt=(
            "You are the support triage dispatcher.\n"
            "\n"
            "For every incoming ticket:\n"
            "1. Classify it: BILLING or TECHNICAL.\n"
            "2. Invoke the matching specialist via the Task tool, passing"
            " the full ticket text as the prompt.\n"
            "3. Reply with two labelled lines:\n"
            "   `ROUTED TO:` <specialist name>\n"
            "   `ANSWER:` <the specialist's reply, quoted verbatim>\n"
            "\n"
            "Never answer a ticket yourself — always delegate."
        ),
    )
```

## Step 3 — register the tree

Slots in a `TemplateTree` name the positions in the tree: the `primary`
slot becomes the entry-point agent; every other slot compiles in
subagent mode by default. The tech specialist runs on a different
provider — mixed-model trees compile and run unchanged:

```python
def registry() -> AgentRegistry:
    reg = AgentRegistry()

    triage_id = reg.register_agent(
        "triage", _triage(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.2),
    )
    billing_id = reg.register_agent(
        "billing-specialist", _billing_specialist(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.3),
    )
    tech_id = reg.register_agent(
        "tech-specialist", _tech_specialist(),
        ModelParameters(model_name="local-vllm-remote/qwen35-27b", temperature=0.5),
    )

    reg.register_template(TemplateTree(
        name="support-tpl",
        slots=[
            TemplateSlot(name="primary", default_agent_id=triage_id),
            TemplateSlot(name="billing-specialist", default_agent_id=billing_id),
            TemplateSlot(name="tech-specialist", default_agent_id=tech_id),
        ],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="support-tpl"),
    )
    return reg
```

## Step 4 — compile it

Create `build_agents.py` next to `agents.py`:

```python
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agents import registry
from open_agent_compiler.compiler.script import CompileScript


def main() -> None:
    script = CompileScript(target=HERE / "build", factory=registry,
                           config="prod", clean=True, verbose=True)
    result = script.run()
    print(f"wrote {len(result.written_files)} file(s); slots: {result.resolved_slots}")


if __name__ == "__main__":
    main()
```

## Run it

```bash
uv run python build_agents.py
cd build
opencode run --agent primary "I was charged twice for my subscription this month."
```

The compile step reports one markdown artifact per slot, e.g.:

```
wrote 3 file(s); slots: ['primary', 'billing-specialist', 'tech-specialist']
```

and the run produces a routed answer shaped like:

```
ROUTED TO: billing-specialist
ANSWER: This looks like a duplicate charge from an overlapping renewal. ...
```

Try a technical ticket ("The app crashes on startup after the update")
and watch the routing flip to `tech-specialist`. Peek at
`build/.opencode/agents/primary.md` — its SECURITY POLICY block lists
exactly the two allowed Task targets.

## Why it works

The tree is *data*, not orchestration code: the dispatcher declares its
children as `AgentHeader` references, the `TemplateTree` maps agents
onto named slots, and the compiler emits opencode artifacts where the
Task tool is scoped to precisely the declared subagents. Each
specialist keeps a small single-domain prompt, so adding a fourth
category is one new definition plus one new slot.

## Going further

- Subagents share the parent's session and complete in seconds. For
  long-running or parallel workers with their own identity, reference
  the child with `mode="primary"` instead — the compiler bundles a bash
  dispatcher (`opencode_manager.py`) so the coordinator shells out to a
  fresh session per worker (`examples/50_primary_dispatch`).
- [Workflows and subagents guide](../guides/workflows-and-subagents.md)
- [The agent model](../concepts/agent-model.md)
- [Registry and compilation](../concepts/registry-and-compilation.md)
