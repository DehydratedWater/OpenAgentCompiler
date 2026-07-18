"""ScriptTool stub for the multi-turn monitoring example.

The runtime mock-replaces this; the real handler exists only so the
script vendoring path has something to copy into build/scripts/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic import BaseModel  # noqa: E402

from open_agent_compiler.runtime import ScriptTool  # noqa: E402


class AlertsIn(BaseModel):
    pass


class AlertsOut(BaseModel):
    alerts: list[dict]


class FetchAlertsTool(ScriptTool[AlertsIn, AlertsOut]):
    name = "fetch-alerts"
    description = "Fetch new alerts since last check."

    def execute(self, input: AlertsIn) -> AlertsOut:
        return AlertsOut(alerts=[])


if __name__ == "__main__":
    FetchAlertsTool.run()
