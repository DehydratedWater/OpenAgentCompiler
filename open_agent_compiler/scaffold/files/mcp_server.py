"""`app/mcp_server.py` + `mcp_server_run.py` generators.

Emitted when `ScaffoldConfig.with_mcp_server` is True. Exposes the
project's compiled agents as MCP tools so any MCP-aware client
(another opencode session, Claude Desktop, a custom orchestrator)
can call them with the same {prompt, mode, variant, retry, context}
shape the FastAPI accepts. Under the hood both surfaces share
`dispatch_run`, so calling modes / variants / retry chains behave
identically across the two protocols.
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_mcp_server_module(config: ScaffoldConfig) -> str:
    persistence_flag = "True" if config.with_postgres else "False"
    return f'''"""MCP server exposing {config.project_name}'s compiled agents as tools.

Each agent under build/.opencode/agents/ becomes one MCP tool whose
arguments mirror AgentRunRequest. The same dispatch_run that backs
the FastAPI route handles mode / variant / retry; an MCP call with
mode='async' returns a TaskHandle-shaped payload the client polls
through the FastAPI /runs/{{run_id}}/await endpoint.

Run locally over stdio (the default MCP transport):

    uv run python mcp_server_run.py

Point an MCP-aware client at this command; the client sees one tool
per compiled agent (auto-discovered at server start).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.agent_runner import list_compiled_agents, run_agent
from app.dispatch import dispatch_run
from app.models import AgentRunRequest, RetryPolicy

# `_WITH_PERSISTENCE` mirrors the postgres-on flag from the scaffold;
# True routes every MCP-triggered run through app.persistence.record_run
# so the `runs` table sees MCP invocations alongside HTTP ones.
_WITH_PERSISTENCE: bool = {persistence_flag}

server = FastMCP("{config.project_name}-agents")


def _make_handler(agent_name: str):
    """Build a per-agent handler closure that calls dispatch_run.

    Defined as a factory so the agent_name is captured cleanly per
    registration instead of all closures sharing the last loop value.
    """
    async def _invoke(
        prompt: str,
        mode: str = "sync",
        variant: str | None = None,
        retry: dict[str, Any] | None = None,
        context: dict[str, str] | None = None,
        timeout_s: float = 300.0,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """Run an agent via the same dispatcher as the FastAPI route."""
        req = AgentRunRequest(
            prompt=prompt, mode=mode, variant=variant,
            retry=RetryPolicy(**retry) if retry else None,
            context=context, timeout_s=timeout_s,
            callback_url=callback_url,
        )
        result = await dispatch_run(
            agent_name, req, run_agent,
            with_persistence=_WITH_PERSISTENCE,
        )
        return result.model_dump()
    _invoke.__name__ = f"invoke_{{agent_name.replace('/', '_').replace('-', '_')}}"
    return _invoke


def register_all_agents() -> list[str]:
    """Discover every compiled agent and register it as an MCP tool.

    Returns the list of registered tool names so the caller can log
    or surface them at startup.
    """
    registered: list[str] = []
    for agent_name in list_compiled_agents():
        handler = _make_handler(agent_name)
        server.tool(
            name=agent_name,
            description=(
                f"Invoke the {{agent_name!r}} agent in this project."
                f" Arguments mirror AgentRunRequest: prompt (required),"
                f" mode (sync/async/fire_and_forget), variant, retry,"
                f" context, timeout_s, callback_url."
            ),
        )(handler)
        registered.append(agent_name)
    return registered


# Eagerly register at import time so any client that imports the
# module sees the tools right away.
_REGISTERED = register_all_agents()
'''


def render_mcp_server_run(config: ScaffoldConfig) -> str:
    return f'''"""Stdio entry point for the MCP server.

Run this script and point an MCP-aware client at it:

    uv run python mcp_server_run.py

The FastAPI service can stay running independently — both surfaces
share the same compiled agents and dispatcher.
"""

from __future__ import annotations

from app.mcp_server import server, _REGISTERED


if __name__ == "__main__":
    print(
        f"[{config.project_name}] mcp server starting"
        f" — exposing {{len(_REGISTERED)}} agent(s): {{_REGISTERED}}",
    )
    server.run()
'''
