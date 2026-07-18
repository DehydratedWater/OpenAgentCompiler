"""Per-test-kind runners.

- capability.py: introspect compiled permissions / skills against a CapabilityTest.
- tool.py    (Phase 5.4): exercise a tool's handler under a mock binding.
- agent.py   (Phase 5.4+): drive an agent invoker against an AgentTest.
"""

from open_agent_compiler.testing.runner.capability import CapabilityRunResult, run_capability_test
from open_agent_compiler.testing.runner.tool import ToolRunResult, run_tool_test

__all__ = [
    "CapabilityRunResult", "run_capability_test",
    "ToolRunResult", "run_tool_test",
]
