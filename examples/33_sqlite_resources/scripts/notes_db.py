"""ScriptTool that uses Phase 15's resources signature for SQLite.

Run directly to see resource handle in action:

    # Add a note
    OAC_RESOURCES_JSON='{"notes_db":{"kind":"sqlite","config":{"path":"/tmp/oac_demo.db"}}}' \\
        uv run python examples/33_sqlite_resources/scripts/notes_db.py \\
        --mode add --content "first note from the demo"

    # List notes
    OAC_RESOURCES_JSON='{"notes_db":{"kind":"sqlite","config":{"path":"/tmp/oac_demo.db"}}}' \\
        uv run python examples/33_sqlite_resources/scripts/notes_db.py \\
        --mode list

The `OAC_RESOURCES_JSON` env var is the contract the compile
pipeline uses to thread AccessProfile bindings into the runtime —
the framework parses it and constructs ResourceHandle objects the
tool's execute() can use.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic import BaseModel, Field, field_validator  # noqa: E402

from open_agent_compiler.runtime import ResourceHandle, ScriptTool  # noqa: E402


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
    description = "Persistent notes via SQLite (resource-bound)."

    def execute(
        self, input: NotesInput,
        resources: dict[str, ResourceHandle] | None = None,
    ) -> NotesOutput:
        if not resources or "notes_db" not in resources:
            return NotesOutput(ok=False, note="notes_db resource not bound")
        conn = resources["notes_db"].sqlite_connect()
        try:
            conn.execute(
                "create table if not exists notes("
                " id integer primary key autoincrement,"
                " content text not null,"
                " created_at text default current_timestamp)"
            )
            if input.mode == "add":
                if not input.content:
                    return NotesOutput(ok=False, note="content required")
                conn.execute(
                    "insert into notes(content) values (?)", (input.content,),
                )
                conn.commit()
                return NotesOutput(
                    ok=True, note=f"inserted: {input.content[:50]}",
                )
            cur = conn.execute(
                "select id, content, created_at from notes"
                " order by id desc limit ?",
                (input.limit,),
            )
            rows = [
                {"id": r[0], "content": r[1], "created_at": r[2]}
                for r in cur.fetchall()
            ]
            return NotesOutput(ok=True, rows=rows)
        finally:
            conn.close()


if __name__ == "__main__":
    NotesDBTool.run()
