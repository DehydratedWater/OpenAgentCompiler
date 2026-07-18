"""Two agents declaring different MCP server subsets — Phase 12.

Demonstrates `AgentDefinition.mcp_servers` + per-server allowlist
emission. The compile output of each agent only carries its
declared servers; the two agents stay isolated in the same compile.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_agent_compiler import (  # noqa: E402
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    MCPServerDefinition,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)


def _slack_only_agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="slack-bot", name="slack-bot",
            description="Routes messages through Slack MCP only.",
        ),
        usage_explanation_long=(
            "Handles Slack message routing. Has access to the slack"
            " MCP server only — no GitHub, no Linear."
        ),
        usage_explanation_short="slack-only router",
        system_prompt="You route messages through Slack.",
        mcp_servers=[
            MCPServerDefinition(
                name="slack",
                description="Slack workspace messaging.",
            ),
        ],
    )


def _github_only_agent() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="pr-reviewer", name="pr-reviewer",
            description="Reviews PRs via GitHub MCP only.",
        ),
        usage_explanation_long=(
            "Analyses pull requests. Has access to a restricted set of"
            " github MCP tools — can read PRs / list issues but cannot"
            " merge or create."
        ),
        usage_explanation_short="github PR reviewer",
        system_prompt="You analyse PRs and list issues.",
        mcp_servers=[
            MCPServerDefinition(
                name="github",
                description="GitHub repository access.",
                # Per-server tool allowlist — read-only operations only.
                allowed_tools=["read_pr", "list_issues", "list_files"],
            ),
        ],
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()
    a_id = reg.register_agent(
        "slack-bot", _slack_only_agent(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )
    b_id = reg.register_agent(
        "pr-reviewer", _github_only_agent(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )
    reg.register_template(TemplateTree(
        name="tpl",
        slots=[
            TemplateSlot(name="primary", default_agent_id=a_id),
            TemplateSlot(name="reviewer", default_agent_id=b_id),
        ],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


def main() -> None:
    """Build the registry, compile each agent, print the MCP block per agent."""
    from open_agent_compiler.compiler.dialects.opencode.compile_permissions import (
        generate_permissions,
    )
    import json
    reg = registry()
    for slot, variant in reg.resolve_config("prod").items():
        perm = generate_permissions(variant)
        mcp = perm["permission"].get("mcp")
        print(f"\n=== {slot} ({variant.agent_definition.header.name}) ===")
        print(f"permission.mcp = {json.dumps(mcp, indent=2)}")


if __name__ == "__main__":
    main()
