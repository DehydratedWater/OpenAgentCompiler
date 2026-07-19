# Your first agent

In this tutorial you'll go from an empty directory to a running agent: define it
in Python, compile it to opencode files, run it, then recompile the identical
definition for two other runtimes. Prerequisites:
[`oac` and the opencode CLI installed](installation.md), plus opencode
authenticated with a model provider.

## 1. Create a project directory

```bash
mkdir hello-agent && cd hello-agent
```

## 2. Write `agents.py`

An agent build is a plain Python function (a *factory*) that returns an
`AgentRegistry`. Create `agents.py`:

```python
"""One friendly greeter agent."""

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    # 1) WHAT the agent is: full behavioral definition, runtime-agnostic.
    greeter = AgentDefinition(
        header=AgentHeader(
            agent_id="greeter",
            name="greeter",
            description="Says hello back with a warm one-line greeting.",
        ),
        usage_explanation_long=(
            "A minimal agent for smoke tests. Responds to any message"
            " with a single friendly sentence, using the user's name"
            " when mentioned."
        ),
        usage_explanation_short="warm greeting in one sentence",
        system_prompt=(
            "You are a friendly greeter. Reply with exactly one short,"
            " warm sentence. If the user mentioned their name, use it."
            " Do not ask follow-up questions."
        ),
    )

    # 2) Register it with model parameters -> yields an agent id.
    agent_id = reg.register_agent(
        "greeter",
        greeter,
        ModelParameters(
            model_name="anthropic/claude-sonnet-4-5",
            temperature=0.7,
        ),
    )

    # 3) The SHAPE of the deployment: named slots filled by agent ids.
    reg.register_template(
        TemplateTree(
            name="hello-tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )

    # 4) A named selection of that shape ("prod", "ci", "cheap", ...).
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="hello-tpl"),
    )
    return reg
```

The three-layer split — definition, template tree, compilation config — is what
lets one registry serve many deployments; the
[agent model page](../concepts/agent-model.md) covers each layer in depth.

## 3. Compile it

```bash
oac compile agents:registry --config prod --target build --clean
```

`agents:registry` is a `module:callable` spec — the current directory is put on
the import path, so this works from the project root with no install step.
Expected output:

```text
oac compile: wrote 1 slot(s) -> build
```

## 4. Inspect what was generated

The opencode dialect writes one Markdown file per template slot under
`build/.opencode/agents/`. Look at `build/.opencode/agents/primary.md`:

```markdown
---
description: Says hello back with a warm one-line greeting.
model: anthropic/claude-sonnet-4-5
mode: primary
permission:
  '*': deny
tool:
  read: false
  write: false
  edit: false
  task: false
  todoread: false
  todowrite: false
  mcp: false
---

# greeter

Says hello back with a warm one-line greeting.

You are a friendly greeter. Reply with exactly one short, warm sentence. ...
```

Two things to notice:

- The YAML frontmatter carries the model, the mode, and a **deny-by-default**
  permission block — you granted no tools, so none are enabled. Tools, skills,
  and workflows you add to the `AgentDefinition` all land here and in the body
  (see the [tools guide](../guides/tools.md)).
- The body is the compiled system prompt: header, description, then your
  `system_prompt`.

## 5. Run it

opencode discovers agents from the directory containing `.opencode/`, so run
from inside `build/`:

```bash
cd build
opencode run --agent primary "Hi, I'm Dana"
```

You should get back a single warm sentence that uses the name. (If the command
hangs or errors, see [troubleshooting](../reference/troubleshooting.md).)

## 6. Same tree, different runtime

The definition you wrote is runtime-agnostic. Recompile it for Claude Code or
pi by changing one flag:

```bash
cd ..
oac compile agents:registry --config prod --target build-claude --dialect claude --clean
oac compile agents:registry --config prod --target build-pi     --dialect pi     --clean
```

The claude build emits a `.claude/` tree; the pi build emits `.pi/agents/*.md`
with pi-style `tools:` frontmatter. `oac info --dialects` lists everything
registered, including any dialect you plug in yourself. The mapping details
live in [the opencode dialect page](../dialects/opencode.md).

## Where to go next

- **Skip the boilerplate** — `oac init` scaffolds all of this plus Docker,
  FastAPI, and cron: [Project scaffolding](project-scaffold.md)
- **Give the agent tools** — bash allowlists and typed ScriptTools:
  [Tools guide](../guides/tools.md)
- **Test it without burning tokens** — embedded tests with mocks:
  [Testing guide](../guides/testing.md)
- **Let it improve itself** — mutate, score, promote:
  [Improvement loop](../guides/improvement-loop.md)
- **Understand the layers** — [Agent model](../concepts/agent-model.md) and
  [execution tiers](../concepts/execution-tiers.md)
