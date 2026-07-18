"""`tools/notes_db.py` + `agents/access_profile.py` generators.

Emitted when `ScaffoldConfig.with_sqlite` is True. Demonstrates the
Phase-15 resources pattern: a ScriptTool whose `execute` declares
`(input, resources)` and pulls a sqlite3 connection from the
ResourceHandle bound by the active AccessProfile.

Real users would extend the generated tool with their domain logic
(transcript ingest, monitoring notes, conversation memory, etc.).
The scaffold ships a thin "add a note + list recent notes" pattern
so the runtime wiring is exercisable from day one.
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_notes_db_tool(config: ScaffoldConfig) -> str:
    return '''"""Notes-DB ScriptTool — demonstrates the AccessProfile/ResourceHandle path.

`add` mode inserts a note; `list` mode returns the most recent N.
The tool declares `requires_resources=["notes_db"]`; the active
AccessProfile must bind that name to a sqlite kind. The compile
pipeline validates the binding and the runtime supplies the handle.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

from open_agent_compiler.runtime import ResourceHandle, ScriptTool  # noqa: E402


class NotesInput(BaseModel):
    mode: Literal["add", "list"] = Field(
        description="`add` to insert a note; `list` to return recent notes.",
    )
    content: str = Field(
        default="",
        description="Note body (required for `add`).",
    )
    limit: int = Field(
        default=10,
        description="Number of notes returned by `list`.",
    )


class NotesOutput(BaseModel):
    ok: bool
    rows: list[dict] = Field(default_factory=list)
    note: str = ""


class NotesDBTool(ScriptTool[NotesInput, NotesOutput]):
    name = "notes-db"
    description = (
        "Persistent note store backed by SQLite via the framework's"
        " AccessProfile binding. Add or list notes."
    )

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
                    return NotesOutput(ok=False, note="content required for add")
                conn.execute(
                    "insert into notes(content) values (?)", (input.content,),
                )
                conn.commit()
                return NotesOutput(ok=True, note=f"inserted: {input.content[:60]}")
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
'''


def render_access_profile(config: ScaffoldConfig) -> str:
    return f'''"""AccessProfile bindings for {config.project_name}.

The notes-db tool declares `requires_resources=["notes_db"]`; this
module exposes the matching binding so the active profile resolves
cleanly at compile time.

For tests, override with the `:memory:` binding (or use a
MockProfile that covers the tool). For production, point the path
at a real on-disk SQLite file.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler import AccessProfile, ResourceBinding

PROFILES: tuple[AccessProfile, ...] = (
    AccessProfile(
        name="prod",
        bindings={{
            "notes_db": ResourceBinding(
                kind="sqlite",
                config={{"path": str(Path("data/notes.db").resolve())}},
            ),
        }},
    ),
    AccessProfile(
        name="ci",
        bindings={{
            "notes_db": ResourceBinding(
                kind="sqlite", config={{"path": ":memory:"}},
            ),
        }},
    ),
)
'''
