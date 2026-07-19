# Pi Exploration Agent Example

Demonstrates an orchestrator that delegates codebase exploration to pi's
built-in **Explore** agent via the `Agent()` tool.

## What it shows

- Using pi's built-in Explore agent type (not a custom agent)
- Read-only exploration pattern
- Workflow with subagent spawning
- Synthesis of exploration results

## Compile

```bash
uv run python examples/81_pi_exploration/build_agents.py
```

## Run with pi

```bash
cd examples/81_pi_exploration/build
pi run --agent explorer-orchestrator "Find all files that handle authentication"
```

The orchestrator will spawn pi's Explore agent to investigate, then
synthesize the findings.

## Pi's Built-in Agent Types

Pi-subagents provides three built-in agent types:

| Type | Tools | Model | Use Case |
|------|-------|-------|----------|
| `general-purpose` | All 7 | Inherit parent | General tasks, parent twin |
| `Explore` | read, grep, find, ls | haiku | Fast codebase exploration |
| `Plan` | read, grep, find, ls | inherit | Implementation planning |

You can also define custom agent types in `.pi/agents/*.md`.

## Runtime Requirements

The pi runtime must run with two extensions: `@tintinweb/pi-subagents`
(the `Agent()` spawn tool) and `pi-permission-system` (permission
enforcement for the compiled `tools:` allowlists):

```bash
pi install npm:@tintinweb/pi-subagents
pi install npm:pi-permission-system
```

## See Also

- `examples/80_pi_agents/` — custom subagents compiled from Python definitions
- https://pi.dev/packages/@tintinweb/pi-subagents — pi-subagents docs
- https://github.com/MasuRii/pi-permission-system — pi-permission-system docs
