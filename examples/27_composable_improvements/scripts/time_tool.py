"""ScriptTool that returns the current UTC time + optional timezone offset.

Demonstrates the canonical ScriptTool pattern: Pydantic Input/Output
schemas, a ScriptTool subclass with execute(), an optional
mock_response() for tests, and the `if __name__ == '__main__': .run()`
guard so opencode can invoke it as a bash subprocess.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the framework importable when the script runs as a subprocess.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic import BaseModel, Field  # noqa: E402

from open_agent_compiler.runtime import ScriptTool  # noqa: E402


class TimeInput(BaseModel):
    timezone_hours: int = Field(
        default=0,
        description="Offset from UTC in hours (e.g. 1 for CET, -8 for PST).",
    )


class TimeOutput(BaseModel):
    iso: str = Field(description="ISO-8601 timestamp.")
    timezone_hours: int = Field(description="Echoes the requested offset.")
    note: str = Field(default="", description="Optional commentary.")


class TimeTool(ScriptTool[TimeInput, TimeOutput]):
    name = "time-tool"
    description = (
        "Return the current time as an ISO-8601 string with an optional"
        " timezone offset in hours."
    )

    def execute(self, input: TimeInput) -> TimeOutput:
        tz = timezone(timedelta(hours=input.timezone_hours))
        now = datetime.now(tz=tz)
        return TimeOutput(
            iso=now.isoformat(timespec="seconds"),
            timezone_hours=input.timezone_hours,
        )

    def mock_response(self, input: TimeInput) -> TimeOutput | None:
        # Test/dry-run friendly: a deterministic value.
        return TimeOutput(
            iso=f"2026-05-17T12:00:00+{input.timezone_hours:02d}:00",
            timezone_hours=input.timezone_hours,
            note="mock",
        )


if __name__ == "__main__":
    TimeTool.run()
