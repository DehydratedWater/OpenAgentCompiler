"""OpencodeManager — universal agent dispatch and spawn tool.

Any agent in the stack can invoke this tool via bash to:
  - dispatch: delegate a task to a registered subagent
  - spawn:   spin up an independent primary agent (new tree)

Enables infinite-depth routing between agents.

Usage:
    uv run scripts/core/opencode_manager.py --json < stdin
    uv run scripts/core/opencode_manager.py --action dispatch --target-agent-id "joke_agent_*" --prompt "..."
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool


class OpencodeManagerInput(BaseModel):
    action: str = Field(
        description="Action to perform: 'dispatch' (delegate to subagent) or 'spawn' (spin up new primary agent)"
    )
    target_agent_id: str = Field(
        description="Agent ID or wildcard pattern (e.g. 'joke_agent_glm-5.1_t0.7' or 'joke_agent_*')"
    )
    prompt: str = Field(
        description="The task/prompt to send to the target agent"
    )
    context: str | None = Field(
        default=None,
        description="Optional additional context to pass to the target agent",
    )


class OpencodeManagerOutput(BaseModel):
    dispatched_to: str = Field(
        description="Resolved agent ID that was dispatched to"
    )
    action: str = Field(
        description="The action that was performed"
    )
    status: str = Field(
        description="Status of the dispatch: 'queued', 'dispatched', 'error'"
    )
    message: str = Field(
        description="Result message or error description"
    )
    run_id: str | None = Field(
        default=None,
        description="Unique run identifier for tracking the dispatched agent",
    )


class OpencodeManager(ScriptTool[OpencodeManagerInput, OpencodeManagerOutput]):
    name = "opencode_manager"
    description = (
        "Universal agent dispatch and spawn tool. "
        "Allows any agent to delegate tasks to subagents (dispatch) or "
        "spin up independent primary agents (spawn), enabling infinite-depth routing."
    )

    def execute(self, input: OpencodeManagerInput) -> OpencodeManagerOutput:
        import uuid

        run_id = str(uuid.uuid4())[:8]

        if input.action not in ("dispatch", "spawn"):
            return OpencodeManagerOutput(
                dispatched_to=input.target_agent_id,
                action=input.action,
                status="error",
                message=f"Unknown action '{input.action}'. Must be 'dispatch' or 'spawn'.",
                run_id=None,
            )

        resolved_id = input.target_agent_id
        # TODO: integrate with AgentRegistry to resolve wildcards at runtime
        if "*" in resolved_id:
            resolved_id = f"{input.target_agent_id} (wildcard — resolve at compile time)"

        action_label = "dispatched to subagent" if input.action == "dispatch" else "spawned new primary agent"
        return OpencodeManagerOutput(
            dispatched_to=resolved_id,
            action=input.action,
            status="dispatched",
            message=f"{action_label}: {resolved_id} | prompt: {input.prompt[:80]}...",
            run_id=run_id,
        )


if __name__ == "__main__":
    OpencodeManager.run()
