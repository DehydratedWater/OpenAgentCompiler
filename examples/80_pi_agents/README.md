# Pi Agent Example

Demonstrates compiling an agent tree for the pi runtime using the
`@tintinweb/pi-subagents` extension.

> **Runtime requirements:** pi must run with two extensions — 
> `@tintinweb/pi-subagents` (the `Agent()` spawn tool) **and**
> `pi-permission-system` (enforces the compiled `tools:` /
> `disallowed_tools:` frontmatter at tool-call time):
>
> ```bash
> pi install npm:@tintinweb/pi-subagents
> pi install npm:pi-permission-system
> ```

## What it shows

- An orchestrator agent that delegates to two subagents via pi's `Agent()` tool
- Subagent references in the compiled prompt
- Workflow rendering for pi agents
- Model assignment per agent (sonnet for orchestrator, haiku for subagents)
- Tool mapping from OAC's tool model to pi's frontmatter `tools:` field

## Compile

```bash
uv run python examples/80_pi_agents/build_agents.py
```

This produces `.pi/agents/*.md` files in `examples/80_pi_agents/build/`.

## Run with pi

```bash
cd examples/80_pi_agents/build
pi run --agent orchestrator "Summarize and critique this claim: ..."
```

Or spawn subagents directly:

```bash
pi run --agent summarizer "Summarize this text: ..."
pi run --agent critic "Critique this claim: ..."
```

## Compiled output structure

```
build/
└── .pi/
    └── agents/
        ├── orchestrator.md    # Primary orchestrator with workflow
        ├── summarizer.md      # Subagent: text summarizer
        └── critic.md          # Subagent: contrarian reviewer
```

Each `.md` file has YAML frontmatter declaring tools, model, and skills,
followed by the system prompt body.

## Pi agent format

```yaml
---
description: Routes user input through summarizer + critic.
tools: read, bash, task
model: anthropic/claude-sonnet-4-20250514
skills: skill1, skill2
prompt_mode: replace
---

# orchestrator

You orchestrate two specialists.
...
```

## See also

- `examples/40_subagents/` — same pattern compiled for OpenCode
- `examples/50_primary_dispatch/` — primary→primary dispatch for OpenCode
- https://pi.dev/packages/@tintinweb/pi-subagents — pi-subagents extension docs
