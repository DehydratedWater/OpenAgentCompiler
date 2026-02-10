"""Data types for multi-turn conversation scenario tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from open_agent_compiler.testing.scenario import LLMCriterion, ToolCommand, VerifyStep


class MessageRoute(StrEnum):
    """How a message gets routed in production."""

    SLASH_COMMAND = "slash_command"
    ORCHESTRATOR = "orchestrator"


@dataclass
class ConversationMessage:
    """A single message in a multi-turn conversation.

    Route is auto-detected from ``text``: messages starting with ``/``
    are slash commands, everything else goes to the orchestrator.
    """

    text: str
    verify_steps: list[VerifyStep] = field(default_factory=list)
    llm_criteria: list[LLMCriterion] = field(default_factory=list)
    timeout: int = 1800
    description: str = ""

    @property
    def route(self) -> MessageRoute:
        """Auto-detect route from message text."""
        if self.text.startswith("/"):
            return MessageRoute.SLASH_COMMAND
        return MessageRoute.ORCHESTRATOR


@dataclass
class ConversationScenario:
    """Multi-turn conversation test scenario.

    Parameters
    ----------
    name:
        Human-readable scenario name.
    description:
        What this conversation tests.
    messages:
        Ordered list of user messages to send sequentially.
    orchestrator_agent:
        Agent path for non-command messages (e.g. "persona/fren_orchestrator").
    workflow_command_map:
        Maps command name → agent path (e.g. {"goal": "workflows/goal"}).
        If empty, the runner's default map is used.
    seed_commands:
        Tool commands to run before the first message (DB seeding).
    final_verify_steps:
        Verification steps run after all messages complete.
    flow_llm_criteria:
        LLM criteria evaluated against the combined flow log.
    """

    name: str
    description: str
    messages: list[ConversationMessage]
    orchestrator_agent: str = "persona/fren_orchestrator"
    workflow_command_map: dict[str, str] = field(default_factory=dict)
    seed_commands: list[ToolCommand] = field(default_factory=list)
    final_verify_steps: list[VerifyStep] = field(default_factory=list)
    flow_llm_criteria: list[LLMCriterion] = field(default_factory=list)
