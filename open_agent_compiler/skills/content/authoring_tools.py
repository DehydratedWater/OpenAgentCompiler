"""authoring-tools skill — ScriptTool, MockableTool, AccessProfile."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Authoring tools

A tool is anything the agent calls to take action: search a DB, hit an
API, run a shell command, transform a file. The framework gives you
three layers:

1. **`ScriptTool`** — the runtime base class your handler subclasses.
2. **`ToolDefinition`** — metadata + bash/json invocation contract +
   optional default mock + optional resource requirements.
3. **`SkillDefinition`** — bundles related tools into a unit the
   agent's workflow can reference.

## Writing a ScriptTool

```python
# scripts/my_tool.py
from pydantic import BaseModel, Field
from open_agent_compiler.runtime import ScriptTool

class Input(BaseModel):
    query: str = Field(description="The search query")
    limit: int = Field(default=10, description="Max results")

class Output(BaseModel):
    results: list[str]

class MyTool(ScriptTool[Input, Output]):
    name = "my-tool"
    description = "Search the corpus."

    def execute(self, input: Input) -> Output:
        # Real work here.
        return Output(results=["a", "b"])

    def mock_response(self, input: Input) -> Output | None:
        # Optional: deterministic mock for tests.
        return Output(results=["mocked"])

if __name__ == "__main__":
    MyTool.run()
```

`ScriptTool.run()` builds an argparse CLI from the Input model, parses
either `--query "..." --limit 5` or `--json` + stdin, validates, and
executes. The `--mock` flag (or `OAC_MOCK_RESPONSE` env var) makes the
script return a mock instead of calling execute().

## Bash vs JSON tool format

Every tool can carry **both** a `bash_tool` (allowlisted bash command
patterns) and a `json_tool` (OpenCode custom-tool with JSON-schema).
The agent picks per-tool which to emit:

```python
agent = AgentDefinition(
    ...,
    default_tool_format="bash",  # "bash" | "json" | "both"
    tool_format_overrides={"my-tool": "json"},  # per-tool override
)
```

Bash is the default because it's the lowest-friction surface in
OpenCode. Switch to "json" for tools that benefit from typed argument
extraction (long arg lists, polymorphic inputs). "both" is rarely the
right answer — it doubles the prompt budget for the same capability.

## MockableTool: the testing surface

Every tool can declare a default mock inline:

```python
ToolDefinition(
    header=...,
    bash_tool=...,
    mock=MockResponse(
        kind="fixed",
        fixed_output={"results": ["a"]},
    ),
    # ... or kind="echo" or kind="callable" with callable_spec
)
```

A `MockProfile` registered on the registry can override per-tool mocks
for a specific test scenario (e.g. an "all-tools-succeed" CI profile).
When a test specifies `mock_profile`, the runner uses the profile's
response if present, falling back to the tool's default mock, then to
the real handler.

## AccessProfile: resource routing

Tools that touch external systems declare them symbolically:

```python
ToolDefinition(
    header=...,
    requires_resources=["goal_db", "telegram_bot"],
    ...
)
```

An `AccessProfile` binds those names to concrete adapters:

```python
prod = AccessProfile(
    name="prod",
    bindings={
        "goal_db": ResourceBinding(
            kind="postgres", config={"dsn": "..."},
        ),
        "telegram_bot": ResourceBinding(
            kind="api", config={"token_env": "BOT_TOKEN"},
        ),
    },
)
```

Profiles compose via `extends`. The compile invocation picks one profile
per pass via `CompileScript.access_profile="prod"`. A test profile can
swap a real DB for SQLite-in-memory, mark some resources `mock_only`
(unusable without a covering MockProfile), and the compiler validates
every required resource is bound.

## Choosing between bash and the json tool block

| Symptom | Use |
|---------|-----|
| Tool has 1-3 simple args, user reads commands | bash |
| Tool has 10+ args or polymorphic shapes | json |
| Model in production is small (7-13B) and struggles with json | bash |
| Model uses custom_tool format better (some Anthropic / DeepSeek runs) | json |

## `execute(input, resources)` — typed DB / API bindings (Phase 15)

Tools that need a DB / API client can opt into a second `resources`
kwarg on `execute()`:

```python
from open_agent_compiler.runtime import ResourceHandle, ScriptTool

class NotesDBTool(ScriptTool[NotesInput, NotesOutput]):
    name = "notes-db"
    description = "Persistent notes via SQLite resource binding."

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
```

The runtime parses `OAC_RESOURCES_JSON` from env at startup into
`ResourceHandle` objects keyed by symbolic name.
`ResourceHandle.sqlite_connect()` opens a real `sqlite3.Connection`
from `binding.config["path"]`; raises clearly on wrong kind or
mock_only bindings.

Legacy `(self, input)` signatures keep working — the runtime
inspects the signature and only passes `resources=` when declared.

For Postgres-backed tools, the pragmatic path is still
`from db.session import session_scope` directly inside `execute()`.
Example 33 (`33_sqlite_resources/`) is the runnable demo.

## `SpawnAgentTool` — [agent 1] → tool → [agent 2] composition (Phase 21)

Typed wrapper around `uv run scripts/opencode_manager.py run --agent X`:

```python
from open_agent_compiler import SpawnAgentTool, SpawnAgentInput

out = SpawnAgentTool().execute(SpawnAgentInput(
    agent_name="number-cruncher-primary",  # use the -primary twin
    prompt="What is 6 * 7?",
    context={"user_id": "alice"},
    spawn_async=True,  # don't block; returns TaskHandle
))
print(out.task.run_id, out.task.poll_url)
```

Two modes:
- `spawn_async=False`: block until done. Best for short workers.
- `spawn_async=True`: fire-and-forget; returns running TaskHandle
  with `poll_url`. The FastAPI's `/runs/{id}/await` drains later.

The target agent must be primary-mode. Use the `also_compile_as_primary=True`
slot flag (see `authoring-agents`) so a subagent is reachable BOTH ways.

Example 31 (`31_spawn_agent/`) is the runnable demo.

## Skill-bundling pattern (from a ~105-agent production fleet)

Wrap related tools into one named skill rather than wiring N tools
directly into the agent. One production fleet's 105 agents share 72 skill factories
— each skill bundles 1-4 tools with cross-tool rules:

```python
def chat_history_skill() -> SkillDefinition:
    return SkillDefinition(
        name="chat-history",
        description="Read recent chat + write new messages.",
        usage_explanation_long="...",
        usage_explanation_short="chat read/write",
        rules=["Always check the last 24h before adding context."],
        workflow_steps=[
            WorkflowStep(header="Check recent",
                         tools_used=[chat_history_read_tool()]),
            WorkflowStep(header="Append new",
                         tools_used=[chat_message_save_tool()]),
        ],
        positive_examples=[], negative_examples=[],
    )
```

Group tools by *intent* (the agent thinks "I want chat history
awareness"), not by file location. The agent's `skills=[]` list
becomes its capability inventory.

See also: `writing-tests`, `providers-and-models`, `tool-variants`
(catalogue of 6 patterns), `prompt-structure` (volatility tiers).
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="authoring-tools",
        description=(
            "ScriptTool base class, bash vs JSON tool format, MockableTool"
            " surface, AccessProfile resource routing, when to pick which."
        ),
        body_markdown=BODY,
        tools_hint=("ScriptTool", "ToolDefinition", "MockResponse", "AccessProfile"),
    )
