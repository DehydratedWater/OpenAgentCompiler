"""tool-variants skill — the catalogue of tool patterns the framework supports."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Tool variants — every pattern the framework supports

When you decide to give an agent a new capability, the question is
*what shape does the tool take*. The framework supports five
patterns; this skill is the catalogue.

## Pattern 1 — Bash allowlist tool

The agent calls a shell command directly. The compiled artifact
emits a `permission.bash["<pattern>"]: allow` line; everything else
in the bash namespace stays denied.

Best for: scripts you already have, simple deterministic CLIs,
anything where typed I/O isn't worth the schema.

```python
ToolDefinition(
    header=ToolDefinitionHeader(
        name="curl-weather",
        description="Fetch current weather for a city.",
        usage_explanation_long="Pass --city as a quoted CLI flag.",
        usage_explanation_short="weather lookup",
        rules=["Always quote --city values."],
    ),
    bash_tool=ToolDefinitionLogicBash(
        permission_bash=BashToolPermission(
            tool_name="bash", value="allow",
            allowed_commands=["uv run scripts/weather.py *"],
        ),
        positive_examples=["uv run scripts/weather.py --city London"],
        negative_examples=["curl https://api.weatherapi.com/..."],
        mode_specific_rules=[],
    ),
)
# Pair with default_tool_format="bash" on the agent.
```

## Pattern 2 — JSON-schema custom tool

The agent calls a typed function via OpenCode's `custom_tools`
block. The compiled artifact derives a JSON schema from the
ScriptTool's Pydantic Input/Output and emits it under `custom_tools`.

Best for: tools where the model benefits from typed args (numbers,
enums, dicts), or where you want the same handler reachable from
multiple frontends (the JSON contract is portable).

```python
ToolDefinition(
    header=ToolDefinitionHeader(name="weather", description="…", …),
    json_tool=ToolDefinitionLogicJson(
        permission_json=JsonToolPermission(
            tool_name="custom_tool", value="allow",
        ),
        positive_examples=["weather(city='London')"],
        negative_examples=[],
        mode_specific_rules=[],
        tool_scripts=[
            ToolScriptDefinition(
                paths=[HERE / "scripts" / "weather.py"],
                scripts=[ScriptDefinition(
                    target_file_path=Path("scripts/weather.py"),
                    source_file_path=HERE / "scripts" / "weather.py",
                    source_file_type="python",
                    script_contents=None,
                )],
            ),
        ],
    ),
)
# Pair with default_tool_format="json" on the agent.
```

## Pattern 3 — Both bash AND JSON

The same handler exposed two ways. Different agents in the same
compile can pick different formats; you can also drive the
improvement loop's `ToolFormatMutator` to learn which form a given
model performs best with.

```python
ToolDefinition(
    header=...,
    bash_tool=ToolDefinitionLogicBash(...),
    json_tool=ToolDefinitionLogicJson(...),
)
# default_tool_format="both" makes both contracts emit;
# "bash" or "json" picks one even when both are present.
```

The runtime layer for the JSON path is `ScriptTool[Input, Output]`;
the bash path runs the same module's `__main__` block via
`if __name__ == '__main__': MyTool.run()` (the ScriptTool base
emits argparse from the Pydantic schema, so one Python file
serves both contracts).

## Pattern 4 — Python script wrapped as a JSON tool

When you already have a working Python script and you want to give
the model the JSON-schema surface without rewriting:

  1. Subclass `ScriptTool[InputModel, OutputModel]` — re-use the
     existing functions inside `execute()`.
  2. Drop `if __name__ == '__main__': MyTool.run()` at module bottom.
  3. Reference the script from `json_tool.tool_scripts` so the
     compiler auto-vendors it under `build/scripts/`.

Examples 27 (composable improvements) and 30 (tools gallery) both
demonstrate this. Notice how the Pydantic schema declares
`description=` on each Field — those become the JSON-schema `description`
text the model sees.

## Pattern 5 — Long-running tool (TaskHandle return)

When a tool may take more than 30s, return a TaskHandle from
`execute()` instead of blocking. The framework's runtime detects
the type and registers the handle so the caller can poll
`/runs/{run_id}/await` (Phase 20). Two sub-variants:

**5a. Blocking spawn** — a tool that internally spawns a subprocess
(e.g., a slow data ingest) and blocks the caller until done.
Looks the same as Pattern 2 / 3 / 4 from the agent's perspective —
the typed Output is returned.

**5b. Fire-and-forget spawn** — the tool's `execute()` returns a
TaskHandle with `status="running"` and `poll_url` set. The agent's
prompt should instruct it to either:
  - poll `/runs/{run_id}/await` itself (multi-turn pattern), or
  - return the handle to the user and let the next turn drain it.

```python
class SlowIngestTool(ScriptTool[IngestIn, IngestOut]):
    def execute(self, input, resources=None):
        run_id = uuid.uuid4().hex
        subprocess.Popen([...], start_new_session=True)
        return IngestOut(
            task=TaskHandle(
                run_id=run_id, kind="long_running_tool",
                status="running", poll_url=f"/runs/{run_id}/await",
            ),
        )
```

## Pattern 6 — Spawn-agent tool

A tool whose job is to spawn another agent. The framework ships
`SpawnAgentTool` (Phase 21) — a Pydantic-typed `ScriptTool` that
encapsulates the bash invocation behind a clean schema:

```python
from open_agent_compiler import SpawnAgentTool, SpawnAgentInput

# When invoked by the parent agent:
out = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="research-deep-dive",
    prompt="Summarise the recent literature on X",
    spawn_async=True,  # don't block
))
# out.task.run_id + out.task.poll_url for the parent agent to poll later.
```

Use this for [agent 1] → tool → [agent 2] composition where the
spawned agent has its own primary identity (its own session, its
own subagents). Different from a Task-tool subagent — that one
shares the parent's session and tool history.

## Picking between patterns

| If you want… | Use… |
|---|---|
| Quickest implementation, deterministic CLI | Pattern 1 (bash) |
| Typed args, structured tool-call model preference | Pattern 2 (json) |
| One handler, two frontends, A/B which works better | Pattern 3 (both) |
| Existing Python script promoted to typed tool | Pattern 4 (wrap) |
| Tool may take minutes | Pattern 5 (TaskHandle return) |
| Tool needs to start a new top-level agent | Pattern 6 (SpawnAgentTool) |

## See also

- `authoring-tools` — base class + the Pydantic Input/Output story.
- `improvement-loop` — `ToolFormatMutator` for measuring bash vs json
  preference; `ToolDescriptionAppendMutator` for tuning tool docs.
- `docker-and-compose` — the runs API for polling long-running and
  spawned work via /runs/{run_id}/await.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="tool-variants",
        description=(
            "The catalogue of tool patterns: bash-only, json-only, both,"
            " python-script-wrapped, long-running-with-TaskHandle, and"
            " spawn-agent-tool. When to pick which."
        ),
        body_markdown=BODY,
        version="1.0.0",
        tools_hint=(
            "ToolDefinition", "ScriptTool", "SpawnAgentTool",
            "TaskHandle", "default_tool_format",
        ),
    )
