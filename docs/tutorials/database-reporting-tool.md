# Tutorial: a database reporting agent that tests without a database

*Mini-project for: `ScriptTool`, resource bindings, and mock-driven tests.*

## The problem

You want an agent that reads a database and writes a daily activity
report — but you don't want the agent free-styling SQL through a bash
tool, or CI needing a live database to prove the agent still works.
The fix is a typed tool with an explicit contract: the agent can only
call your script, the script gets its connection injected from a named
profile, and tests swap in deterministic mocks.

## What you'll build

- A Pydantic-typed **`ScriptTool`** (`notes-db`) reading/writing SQLite
  through an injected resource handle, exposed via a **`ToolDefinition`**
  with an exact bash allowlist, default **`MockResponse`**, and `ToolTest`.
- **`AccessProfile`s** binding `notes_db` to a real file in prod and to
  `:memory:` in CI, plus a **report-writer agent** tested via `oac test`.

Prerequisites: [installation](../getting-started/installation.md).
Stitched together from `examples/30_tools`, `examples/33_sqlite_resources`,
and `examples/32_multi_turn_mocks` in the repo.

## Step 1 — the typed database tool

Create `scripts/notes_db.py`. The `execute(input, resources)` signature
is the key: the framework parses `OAC_RESOURCES_JSON` at script start
and hands you `ResourceHandle`s — no hard-coded connection strings, and
bad input never reaches SQL (Pydantic rejects it at the CLI boundary).

```python
"""scripts/notes_db.py — resource-bound SQLite tool."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from open_agent_compiler.runtime import ResourceHandle, ScriptTool


class NotesInput(BaseModel):
    mode: str = Field(description="Either 'add' or 'list'.")
    content: str = Field(default="", description="Required for `add` mode.")
    limit: int = Field(default=10)

    @field_validator("mode")
    @classmethod
    def _mode_is_known(cls, v: str) -> str:
        if v not in ("add", "list"):
            raise ValueError(f"mode must be 'add' or 'list', got {v!r}")
        return v


class NotesOutput(BaseModel):
    ok: bool
    rows: list[dict] = Field(default_factory=list)
    note: str = ""


class NotesDBTool(ScriptTool[NotesInput, NotesOutput]):
    name = "notes-db"
    description = "Persistent activity notes via SQLite (resource-bound)."

    def execute(
        self, input: NotesInput,
        resources: dict[str, ResourceHandle] | None = None,
    ) -> NotesOutput:
        if not resources or "notes_db" not in resources:
            return NotesOutput(ok=False, note="notes_db resource not bound")
        conn = resources["notes_db"].sqlite_connect()
        try:
            conn.execute(
                "create table if not exists notes(id integer primary key"
                " autoincrement, content text not null,"
                " created_at text default current_timestamp)")
            if input.mode == "add":
                if not input.content:
                    return NotesOutput(ok=False, note="content required")
                conn.execute("insert into notes(content) values (?)",
                             (input.content,))
                conn.commit()
                return NotesOutput(ok=True, note=f"inserted: {input.content[:50]}")
            cur = conn.execute(
                "select id, content, created_at from notes"
                " order by id desc limit ?", (input.limit,))
            rows = [{"id": r[0], "content": r[1], "created_at": r[2]}
                    for r in cur.fetchall()]
            return NotesOutput(ok=True, rows=rows)
        finally:
            conn.close()


if __name__ == "__main__":
    NotesDBTool.run()
```

## Step 2 — expose it as a ToolDefinition with a default mock

In `agents.py`, wrap the script. The `mock` field makes the stack
testable — tests get the fixed rows instead of a real database:

```python
from pathlib import Path

from open_agent_compiler import (
    AccessProfile, AgentDefinition, AgentHeader, AgentRegistry, AgentTest,
    BashToolPermission, CompilationConfig, EqualsEvaluator, JsonToolPermission,
    ModelParameters, MockResponse, ResourceBinding, ScriptDefinition,
    SubstringEvaluator, TemplateSlot, TemplateTree, ToolDefinition,
    ToolDefinitionHeader, ToolDefinitionLogicBash, ToolDefinitionLogicJson,
    ToolScriptDefinition, ToolTest, Turn)

HERE = Path(__file__).resolve().parent


def notes_db_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="notes-db",
            description="Read/write the activity notes database.",
            usage_explanation_long=(
                "Use --mode list to fetch recent rows for the report;"
                " --mode add records a new entry."),
            usage_explanation_short="activity database access",
            rules=["Never query the database any other way."]),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/notes_db.py *"]),
            positive_examples=["uv run scripts/notes_db.py --mode list --limit 20"],
            negative_examples=["sqlite3 data/notes.db 'select *'"],
            mode_specific_rules=["Always use `uv run` to launch the script."]),
        json_tool=ToolDefinitionLogicJson(
            permission_json=JsonToolPermission(tool_name="custom_tool", value="allow"),
            positive_examples=["notes-db(mode='list', limit=20)"],
            negative_examples=[], mode_specific_rules=[],
            tool_scripts=[ToolScriptDefinition(
                paths=[HERE / "scripts" / "notes_db.py"],
                scripts=[ScriptDefinition(
                    target_file_path=Path("scripts/notes_db.py"),
                    source_file_path=HERE / "scripts" / "notes_db.py",
                    source_file_type="python", script_contents=None)])]),
        mock=MockResponse(kind="fixed", fixed_output={
            "ok": True, "note": "mock", "rows": [
                {"id": 2, "content": "deployed v1.3", "created_at": "2026-07-18"},
                {"id": 1, "content": "fixed login bug", "created_at": "2026-07-18"}],
        }),
        requires_resources=["notes_db"],
        tool_tests=[ToolTest(
            name="notes-db-mock-shape", input={"mode": "list"},
            evaluators=(EqualsEvaluator(field="ok", expected=True,
                                        name="mock_rows_ok"),),
        )],
    )


PROFILES = [
    AccessProfile(name="prod", bindings={"notes_db": ResourceBinding(
        kind="sqlite", config={"path": "data/notes.db"})}),
    AccessProfile(name="ci", bindings={"notes_db": ResourceBinding(
        kind="sqlite", config={"path": ":memory:"})}),
]
```

## Step 3 — the reporting agent, with an embedded test

```python
def report_writer() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="daily-reporter", name="daily-reporter",
            description="Writes the daily activity report from the notes DB.",
        ),
        usage_explanation_long=(
            "Lists recent rows via notes-db and formats them as a dated"
            " report with one bullet per entry."),
        usage_explanation_short="daily report writer",
        system_prompt=(
            "You write the daily activity report.\n"
            "1. Call notes-db with mode=list.\n"
            "2. Format the rows as 'DAILY REPORT' + one bullet per entry"
            " (newest first). If no rows, say 'No activity recorded.'"),
        extra_tools=[notes_db_tool()],
        agent_tests=[AgentTest(
            name="report-uses-db", access_profile="ci",
            turns=(Turn(prompt="Write today's report.",
                        expected_tool_calls=("notes-db",),
                        evaluators=(SubstringEvaluator(needle="DAILY REPORT"),)),),
        )],
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent_id = reg.register_agent(
        "daily-reporter", report_writer(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0))
    reg.register_template(TemplateTree(
        name="tpl", slots=[TemplateSlot(name="primary", default_agent_id=agent_id)]))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    return reg
```

## Run it

Exercise the tool directly (resource injected via env), then the tests:

```bash
RESOURCES='{"notes_db":{"kind":"sqlite","config":{"path":"/tmp/report_demo.db"}}}'
OAC_RESOURCES_JSON="$RESOURCES" uv run python scripts/notes_db.py \
    --mode add --content "fixed login bug"
OAC_RESOURCES_JSON="$RESOURCES" uv run python scripts/notes_db.py --mode list

uv run oac test "agents:registry" --config prod -v
```

Expected shape:

```
{"ok": true, "rows": [{"id": 1, "content": "fixed login bug", ...}]}
  pass 'notes-db-mock-shape'
  agent test 'report-uses-db': skipped (requires invoker; not yet wired)
oac test: discovered=2 passed=1 failed=0 skipped=0 not_runnable=1
```

The `ToolTest` ran against the declared mock — no database was touched.
The `AgentTest` is discovered and validated but reported `not_runnable`:
full agent-in-the-loop execution needs a model invoker the CLI doesn't
wire up (its expectations remain executable documentation, and
improvement-loop evaluators can drive it). Re-run `oac test` and green
tests are skipped via the hash cache. For temporal scenarios (empty DB,
then rows, then empty), use a `MockProfile` with a `kind="sequence"`
`MockResponse` and a multi-turn test — see `examples/32_multi_turn_mocks`.

## Why it works

Safety and testability come from the same place: the contract. The
agent only sees an allowlisted command and a typed schema; the script
only sees a `ResourceHandle` resolved from the active `AccessProfile`;
the tests only see the declared `MockResponse`. Swapping prod SQLite
for CI `:memory:` — or for a mock — changes zero lines of agent or
tool code, which is why the suite runs in CI with no infrastructure.

## Going further

- [Tools guide](../guides/tools.md) — bash vs JSON surfaces, bundling.
- [Testing guide](../guides/testing.md) — evaluators, `MockProfile`,
  multi-turn tests, the green-hash cache.
- [Registry and compilation](../concepts/registry-and-compilation.md)
