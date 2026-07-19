# Authoring tools

In this guide you'll build a tool end to end: a `ScriptTool` handler with
typed input/output, a `ToolDefinition` that compiles it into an agent (as a
bash allowlist entry, a JSON-schema custom tool, or both), a deterministic
mock so tests never need credentials, and an `AccessProfile` that routes the
tool to a real database in prod and an in-memory one in CI.

## 1. Write the ScriptTool handler

Every script-backed tool subclasses `ScriptTool[Input, Output]` from
`open_agent_compiler.runtime` and lives in your project's `scripts/`:

```python
# scripts/time_tool.py
from pydantic import BaseModel, Field
from open_agent_compiler.runtime import ScriptTool

class TimeInput(BaseModel):
    timezone_hours: int = Field(default=0, description="Offset from UTC in hours.")

class TimeOutput(BaseModel):
    iso: str
    timezone_hours: int

class TimeTool(ScriptTool[TimeInput, TimeOutput]):
    name = "time-tool"
    description = "Return current UTC time (optional timezone offset)."

    def execute(self, input: TimeInput) -> TimeOutput:
        import datetime
        tz = datetime.timezone(datetime.timedelta(hours=input.timezone_hours))
        return TimeOutput(iso=datetime.datetime.now(tz).isoformat(),
                          timezone_hours=input.timezone_hours)

if __name__ == "__main__":
    TimeTool.run()
```

`ScriptTool.run()` generates an argparse CLI from the input model, so the
compiled agent invokes it as `uv run scripts/time_tool.py --timezone_hours 1`,
or pipes JSON via `--json` + stdin. Output is printed as JSON. The built-in
`--mock` flag (or the `OAC_MOCK_RESPONSE` env var) short-circuits `execute()`
and returns a mock instead — that's what test variants use.

## 2. Bind external systems with `execute(input, resources)`

Tools that touch a DB or API opt into a second `resources` kwarg. The runtime
inspects your signature: the legacy `(self, input)` shape keeps working, and
`(self, input, resources)` receives a `dict[str, ResourceHandle]` parsed from
the `OAC_RESOURCES_JSON` env var:

```python
from open_agent_compiler.runtime import ResourceHandle, ScriptTool

class NotesTool(ScriptTool[NotesInput, NotesOutput]):
    name = "notes-db"
    description = "Persistent notes via a bound SQLite resource."

    def execute(
        self, input: NotesInput,
        resources: dict[str, ResourceHandle] | None = None,
    ) -> NotesOutput:
        if not resources or "notes_db" not in resources:
            return NotesOutput(ok=False)
        conn = resources["notes_db"].sqlite_connect()
        try:
            ...  # use conn
        finally:
            conn.close()
        return NotesOutput(ok=True)
```

`ResourceHandle` carries the binding's `kind` and `config` from the active
AccessProfile. `sqlite_connect()` opens a real `sqlite3.Connection` from
`config["path"]` and raises clearly on a wrong kind or a `mock_only` binding.
`examples/33_sqlite_resources/` is the runnable demo.

## 3. Declare the ToolDefinition

The compile-time side is a `ToolDefinition`. It can carry **both** invocation
contracts — `bash_tool` (an allowlisted bash command) and `json_tool` (an
OpenCode custom tool with a JSON schema derived from your input model):

```python
from open_agent_compiler import (
    BashToolPermission, JsonToolPermission, MockResponse, ScriptDefinition,
    ToolDefinition, ToolDefinitionHeader, ToolDefinitionLogicBash,
    ToolDefinitionLogicJson, ToolScriptDefinition,
)

def time_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="time-tool",
            description="Return current UTC time (optional timezone offset).",
            usage_explanation_long=(
                "Use for any time-related question. Pass an integer hour"
                " offset via --timezone_hours (e.g. 1=CET, -8=PST)."
            ),
            usage_explanation_short="get the current time",
            rules=["Always include a timezone in the answer."],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/time_tool.py *"],
            ),
            positive_examples=["uv run scripts/time_tool.py --timezone_hours 0"],
            negative_examples=["date"],  # never the shell builtin
            mode_specific_rules=["Always use `uv run` to launch the script."],
        ),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=["time-tool(timezone_hours=0)"],
            negative_examples=["time-tool(timezone='UTC')"],  # wrong field/type
            tool_scripts=[ToolScriptDefinition(
                paths=[HERE / "scripts" / "time_tool.py"],
                scripts=[ScriptDefinition(
                    target_file_path=Path("scripts/time_tool.py"),
                    source_file_path=HERE / "scripts" / "time_tool.py",
                    source_file_type="python", script_contents=None,
                )],
            )],
        ),
        mock=MockResponse(kind="fixed", fixed_output={
            "iso": "2026-05-17T12:00:00+00:00", "timezone_hours": 0,
        }),
        requires_resources=[],  # symbolic resource names, e.g. ["notes_db"]
    )
```

The compiler copies each declared script into the build tree's `scripts/`
(inline `script_contents` or a `source_file_path`).

## 4. Pick bash or JSON per agent

The agent chooses which contract to emit via `default_tool_format`
(`"bash"` | `"json"` | `"both"`, default `"bash"`) plus per-tool
`tool_format_overrides={"time-tool": "json"}`. A tool carrying only one
contract always falls back to the one it has.

| Symptom | Use |
|---------|-----|
| 1-3 simple args, humans read the transcripts | bash |
| 10+ args or polymorphic input shapes | json |
| Small production model (7-13B) that fumbles structured calls | bash |
| Model handles the custom_tool format well | json |

`"both"` doubles the prompt budget for the same capability — rarely right.
`examples/30_tools/` compiles one agent with `both` and a sibling with `json`
so you can diff the emitted frontmatter.

## 5. Ship a mock with every tool

The `mock=MockResponse(...)` field is the tool's default testing surface.
Kinds: `fixed` (canned `fixed_output`), `echo` (returns the validated input),
`callable` / `stateful_callable` (a `"module:callable"` spec), and `sequence`
(per-call responses for multi-turn scenarios). A `MockProfile` registered via
`reg.register_mock_profile(...)` overrides per-tool mocks for one scenario;
tests select it by name via their `mock_profile` field. Design rule: **every
tool ships a mock**, so `oac test` runs green with zero credentials. See
[testing](testing.md) and `examples/32_multi_turn_mocks/`.

## 6. Route resources with an AccessProfile

Tools declare external systems symbolically (`requires_resources=["notes_db"]`);
an `AccessProfile` binds those names per environment:

```python
from open_agent_compiler import AccessProfile, ResourceBinding

prod = AccessProfile(name="prod", bindings={
    "notes_db": ResourceBinding(kind="postgres", config={"dsn": "..."}),
})
ci = AccessProfile(name="ci", extends="prod", bindings={
    "notes_db": ResourceBinding(kind="sqlite", config={"path": ":memory:"}),
})
```

Profiles compose via single-parent `extends`. The compile pass selects one via
`CompileScript(..., access_profile="ci", mock_profile="happy-path")`, and the
compiler validates every required resource is bound (or `mock_only` with a
covering MockProfile) before emitting artifacts.

## Bundled infrastructure scripts

The opencode dialect auto-includes three framework scripts under
`build/scripts/` — only when the resolved tree needs them:

| Script | Included when |
|--------|---------------|
| `subagent_todo.py` | any agent has a `workflow` with `todo_mode != "none"` |
| `workspace_io.py` | any agent sets `workspace=...` |
| `opencode_manager.py` | any agent references a `mode="primary"` subagent |

You never declare these as tools; the compiler wires the matching prompt
blocks and bash permissions automatically.

## Surface the exact command verbs

Compiled agents flail — wrong `--command` verbs, `ls` + `--help` exploration —
unless the prompt names the **exact** verbs a ScriptTool accepts. If your tool
dispatches on a `command` field (`init` / `read` / `write` / `list`), derive
that verb list from the field's enum (or a dispatch-table scan) and inject it
verbatim into `usage_explanation_long`, the `positive_examples`, and
`mode_specific_rules`. One concrete invocation line per verb beats any prose
description; keep the examples in sync with the handler so the agent never has
to discover the CLI by trial and error.

## Related pages

- [Agent model concepts](../concepts/agent-model.md)
- [Workflows and subagents](workflows-and-subagents.md)
- [Testing](testing.md) — ToolTest, MockProfile, evaluators
- [Improvement loop](improvement-loop.md)
- [CLI reference](../reference/cli.md)
