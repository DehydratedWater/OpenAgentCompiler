"""Long-running ScriptTool that returns a TaskHandle.

Demonstrates Phase 20's TaskHandle return shape. The tool's
execute() spawns a detached background job, returns immediately
with status='running' + poll_url, and lets the caller drain
later via the FastAPI scaffold's /runs/{run_id}/await endpoint.

Run directly to see the handle shape:

    uv run python examples/29_long_running_task/slow_tool.py

For comparison, a `--blocking` flag exists that simulates a
short tool: blocks until done and returns terminal status.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, Field  # noqa: E402

from open_agent_compiler import ScriptTool, TaskHandle  # noqa: E402


class IngestInput(BaseModel):
    source_url: str = Field(description="URL to ingest.")
    estimated_minutes: float = Field(default=5.0)


class IngestOutput(BaseModel):
    task: TaskHandle
    note: str = ""


class SlowIngestTool(ScriptTool[IngestInput, IngestOutput]):
    name = "slow-ingest"
    description = (
        "Ingest a long document. Returns a TaskHandle when async;"
        " blocks until done when sync."
    )

    def execute(
        self, input: IngestInput, resources=None,
    ) -> IngestOutput:
        run_id = f"ingest_{uuid.uuid4().hex[:12]}"
        async_mode = os.environ.get("INGEST_ASYNC", "1") == "1"
        if async_mode:
            # Real implementation would subprocess.Popen the actual
            # ingest worker here. For the demo we just fabricate the
            # handle so you can see the shape.
            return IngestOutput(
                task=TaskHandle(
                    run_id=run_id,
                    kind="long_running_tool",
                    status="running",
                    poll_url=f"/runs/{run_id}/await",
                    eta_seconds=input.estimated_minutes * 60,
                ),
                note=(
                    "Ingest started in the background. Poll the URL"
                    " or call /runs/{run_id}/await to wait."
                ),
            )
        # Blocking mode — simulate work.
        time.sleep(0.5)
        return IngestOutput(
            task=TaskHandle(
                run_id=run_id, kind="long_running_tool",
                status="success",
                result={"source_url": input.source_url, "chunks": 42},
            ),
            note="Ingest completed.",
        )


if __name__ == "__main__":
    # Bypass the framework's argparse builder so we can demo both modes
    # without the user needing to know the env var.
    p = argparse.ArgumentParser()
    p.add_argument("--blocking", action="store_true")
    p.add_argument("--source_url", default="https://example.com/doc")
    args = p.parse_args()
    if args.blocking:
        os.environ["INGEST_ASYNC"] = "0"
    out = SlowIngestTool().execute(IngestInput(source_url=args.source_url))
    print(out.model_dump_json(indent=2))
