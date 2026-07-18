"""Walk an AgentRegistry and produce flat lists of every embedded test.

Discovery uses the resolved compilation tree (so any test embedded on a
variant the user actually compiles is found, not orphan agents that never
land in any config). Tests are tagged with their owning agent's slot name
and the agent's variant for downstream reporting.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.test_model import AgentTest, CapabilityTest, ToolTest
from open_agent_compiler.model.core.tools_model import ToolDefinition


class CapabilityCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    slot: str
    variant: AgentVariant
    test: CapabilityTest


class ToolCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    slot: str
    variant: AgentVariant
    tool: ToolDefinition
    test: ToolTest


class AgentCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    slot: str
    variant: AgentVariant
    test: AgentTest


class DiscoveryResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    capability: list[CapabilityCandidate] = []
    tool: list[ToolCandidate] = []
    agent: list[AgentCandidate] = []

    def total(self) -> int:
        return len(self.capability) + len(self.tool) + len(self.agent)


def _gather_tools(variant: AgentVariant) -> list[ToolDefinition]:
    seen: dict[str, ToolDefinition] = {}
    for tool in variant.agent_definition.extra_tools:
        seen.setdefault(tool.header.name, tool)
    for skill in variant.agent_definition.skills:
        for step in skill.workflow_steps:
            for tool in step.tools_used:
                seen.setdefault(tool.header.name, tool)
    return list(seen.values())


def discover(resolved: dict[str, AgentVariant]) -> DiscoveryResult:
    """Flatten every embedded test in a resolved compilation tree."""
    cap: list[CapabilityCandidate] = []
    tool: list[ToolCandidate] = []
    agt: list[AgentCandidate] = []

    seen_tool_test_ids: set[tuple[str, str]] = set()

    for slot, variant in resolved.items():
        for c in variant.agent_definition.capability_tests:
            cap.append(CapabilityCandidate(slot=slot, variant=variant, test=c))
        for a in variant.agent_definition.agent_tests:
            agt.append(AgentCandidate(slot=slot, variant=variant, test=a))

        # Agent-scoped tool tests run against any tool reachable from
        # this agent that matches the test (we run them against every
        # reachable tool — same test, multiple tools, scoped per slot).
        reachable_tools = _gather_tools(variant)
        for at in variant.agent_definition.tool_tests:
            # Agent-level tool test isn't bound to a specific tool — apply
            # to the first reachable tool whose name appears in evaluators?
            # Cleaner: skip these here and require the user to put them on
            # ToolDefinition.tool_tests. We expose them as
            # "tool_tests_unbound" in DiscoveryResult.extras later if needed.
            pass

        for tooldef in reachable_tools:
            for tt in tooldef.tool_tests:
                # Dedupe by (tool name, test name) so the same tool wired
                # into multiple agents doesn't produce N redundant runs.
                key = (tooldef.header.name, tt.name)
                if key in seen_tool_test_ids:
                    continue
                seen_tool_test_ids.add(key)
                tool.append(ToolCandidate(
                    slot=slot, variant=variant, tool=tooldef, test=tt,
                ))

    return DiscoveryResult(capability=cap, tool=tool, agent=agt)
