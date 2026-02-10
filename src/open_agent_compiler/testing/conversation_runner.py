"""Conversation runner — executes multi-turn conversation scenarios."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from open_agent_compiler.testing.conversation import (
    ConversationMessage,
    MessageRoute,
)
from open_agent_compiler.testing.runner import (
    AgentRunResult,
    VerifyStepResult,
    _check_assertion,
)

if TYPE_CHECKING:
    from pathlib import Path

    from open_agent_compiler.testing.conversation import ConversationScenario
    from open_agent_compiler.testing.llm_judge import JudgeResult, LLMJudge
    from open_agent_compiler.testing.tool_runner import ToolRunner


@dataclass
class MessageResult:
    """Result of a single message in a conversation."""

    message: ConversationMessage
    agent_path: str
    agent_result: AgentRunResult
    verify_results: list[VerifyStepResult] = field(default_factory=list)
    judge_results: list[JudgeResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        agent_ok = self.agent_result.return_code == 0
        verify_ok = all(v.passed for v in self.verify_results)
        judge_ok = all(j.passed for j in self.judge_results)
        no_fallback = not self.agent_result.subagent_fallback
        return agent_ok and verify_ok and judge_ok and no_fallback


@dataclass
class ConversationResult:
    """Result of a complete multi-turn conversation."""

    scenario: ConversationScenario
    seed_outputs: list[dict[str, Any]]
    message_results: list[MessageResult]
    final_verify_results: list[VerifyStepResult] = field(default_factory=list)
    flow_judge_results: list[JudgeResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def combined_flow_log(self) -> str:
        """Concatenate all message flow logs into one."""
        parts: list[str] = []
        for i, mr in enumerate(self.message_results):
            header = (
                f"--- Message {i + 1}: "
                f"{mr.message.description or mr.message.text[:60]} "
                f"({mr.agent_path}) ---"
            )
            parts.append(header)
            parts.append(mr.agent_result.flow_log)
        return "\n\n".join(parts)

    @property
    def all_passed(self) -> bool:
        messages_ok = all(mr.passed for mr in self.message_results)
        final_ok = all(v.passed for v in self.final_verify_results)
        flow_ok = all(r.passed for r in self.flow_judge_results)
        return messages_ok and final_ok and flow_ok

    def summary(self) -> str:
        """Human-readable summary of the conversation result."""
        lines = [f"Conversation: {self.scenario.name}"]
        lines.append(f"  Total duration: {self.duration_seconds:.1f}s")

        # Seed summary
        seed_ok = sum(1 for s in self.seed_outputs if s.get("success"))
        seed_fail = len(self.seed_outputs) - seed_ok
        if self.seed_outputs:
            lines.append(f"  Seeds: {seed_ok} ok, {seed_fail} failed")

        # Per-message results
        for i, mr in enumerate(self.message_results):
            status = "PASS" if mr.passed else "FAIL"
            desc = mr.message.description or mr.message.text[:60]
            lines.append(
                f"  Message {i + 1} [{status}]: {desc}"
                f" → {mr.agent_path}"
                f" (exit={mr.agent_result.return_code},"
                f" {mr.agent_result.duration_seconds:.1f}s)"
            )
            if mr.agent_result.subagent_fallback:
                lines.append("    [FATAL] Subagent fallback detected")
            for vr in mr.verify_results:
                vs = "PASS" if vr.passed else "FAIL"
                lines.append(
                    f"    [{vs}] verify: {vr.step.command.script}"
                    f" {vr.step.command.args}"
                )
                for ar in vr.assertion_results:
                    s = "PASS" if ar.passed else "FAIL"
                    lines.append(
                        f"      [{s}] {ar.assertion.field}"
                        f" {ar.assertion.operator}"
                        f" {ar.assertion.expected}: {ar.message}"
                    )
                for jr in vr.judge_results:
                    s = "PASS" if jr.passed else "FAIL"
                    lines.append(
                        f"      [{s}] LLM: {jr.criterion}"
                        f" (confidence={jr.confidence:.2f})"
                        f": {jr.reasoning}"
                    )
            for jr in mr.judge_results:
                s = "PASS" if jr.passed else "FAIL"
                lines.append(
                    f"    [{s}] LLM: {jr.criterion}"
                    f" (confidence={jr.confidence:.2f})"
                    f": {jr.reasoning}"
                )

        # Final verify results
        for i, vr in enumerate(self.final_verify_results):
            vs = "PASS" if vr.passed else "FAIL"
            lines.append(
                f"  Final verify {i + 1} [{vs}]:"
                f" {vr.step.command.script} {vr.step.command.args}"
            )
            try:
                formatted = json.dumps(
                    vr.tool_output,
                    indent=2,
                    default=str,
                )
                for line in formatted.splitlines():
                    lines.append(f"    {line}")
            except (TypeError, ValueError):
                lines.append(f"    {vr.tool_output!r}")
            for ar in vr.assertion_results:
                s = "PASS" if ar.passed else "FAIL"
                lines.append(
                    f"    [{s}] {ar.assertion.field}"
                    f" {ar.assertion.operator}"
                    f" {ar.assertion.expected}: {ar.message}"
                )
            for jr in vr.judge_results:
                s = "PASS" if jr.passed else "FAIL"
                lines.append(
                    f"    [{s}] LLM: {jr.criterion}"
                    f" (confidence={jr.confidence:.2f})"
                    f": {jr.reasoning}"
                )

        # Flow-level LLM results
        for jr in self.flow_judge_results:
            s = "PASS" if jr.passed else "FAIL"
            lines.append(
                f"  [{s}] Flow LLM: {jr.criterion}"
                f" (confidence={jr.confidence:.2f})"
                f": {jr.reasoning}"
            )

        # On failure, append flow log excerpts
        if not self.all_passed:
            log = self.combined_flow_log
            excerpt = log[-3000:] if len(log) > 3000 else log
            if len(log) > 3000:
                excerpt = "...(truncated)\n" + excerpt
            lines.append("  --- Flow log excerpt ---")
            lines.append(excerpt)

        return "\n".join(lines)


class ConversationRunner:
    """Executes multi-turn conversation scenarios.

    Composes ``ToolRunner`` and ``LLMJudge`` — same building blocks
    as ``ScenarioRunner`` but with multi-message routing logic.
    """

    def __init__(
        self,
        tool_runner: ToolRunner,
        judge: LLMJudge,
        project_root: Path,
        *,
        orchestrator_agent: str = "persona/fren_orchestrator",
        workflow_command_map: dict[str, str] | None = None,
        attach_url: str | None = None,
    ) -> None:
        self.tool_runner = tool_runner
        self.judge = judge
        self.project_root = project_root
        self.orchestrator_agent = orchestrator_agent
        self.workflow_command_map = workflow_command_map or {}
        self.attach_url = attach_url

    def _resolve_agent(
        self,
        message: ConversationMessage,
        scenario: ConversationScenario,
    ) -> tuple[str, str]:
        """Map a message to (agent_path, prompt).

        Slash commands: ``/goal add Learn piano`` → agent
        ``workflows/goal``, prompt ``add Learn piano``.

        Orchestrator messages: full text goes to the orchestrator agent.
        """
        if message.route == MessageRoute.SLASH_COMMAND:
            # Parse "/cmd rest of text"
            text = message.text.lstrip("/")
            parts = text.split(None, 1)
            cmd = parts[0]
            prompt = parts[1] if len(parts) > 1 else ""

            # Look up in scenario-specific map first, then runner default
            effective_map = {**self.workflow_command_map}
            if scenario.workflow_command_map:
                effective_map.update(scenario.workflow_command_map)

            agent_path = effective_map.get(cmd, f"workflows/{cmd}")
            return agent_path, prompt

        # Orchestrator route — use scenario override or runner default
        orchestrator = scenario.orchestrator_agent or self.orchestrator_agent
        return orchestrator, message.text

    def _run_agent(
        self,
        agent_path: str,
        prompt: str,
        timeout: int,
    ) -> AgentRunResult:
        """Run an agent via opencode CLI (blocking, called from executor)."""
        cmd = ["opencode", "run", "--agent", agent_path]
        if self.attach_url:
            cmd.extend(["--attach", self.attach_url])
        cmd.append(prompt)

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                env=self.tool_runner.env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - t0
            raw_out = exc.stdout or b""
            raw_err = exc.stderr or b""
            stdout = (
                raw_out.decode("utf-8", errors="replace")
                if isinstance(raw_out, bytes)
                else raw_out
            )
            stderr = (
                raw_err.decode("utf-8", errors="replace")
                if isinstance(raw_err, bytes)
                else raw_err
            )
            timeout_msg = f"Agent timed out after {timeout}s"
            flow = stdout + "\n" + stderr
            flow = timeout_msg if not flow.strip() else flow + "\n" + timeout_msg
            return AgentRunResult(
                return_code=124,
                stdout=stdout,
                stderr=stderr,
                flow_log=flow,
                duration_seconds=elapsed,
            )

        elapsed = time.monotonic() - t0
        return AgentRunResult(
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            flow_log=result.stdout + "\n" + result.stderr,
            duration_seconds=elapsed,
        )

    async def _run_verify_step(
        self,
        step: Any,
        agent_result: AgentRunResult | None,
    ) -> VerifyStepResult:
        """Run a single verification step (same logic as ScenarioRunner)."""
        tool_output = self.tool_runner.run(step.command)
        assertion_results = [_check_assertion(tool_output, a) for a in step.assertions]

        judge_results: list[JudgeResult] = []
        if step.llm_criteria:
            context_parts = [
                "Tool output:\n" + json.dumps(tool_output, indent=2, default=str),
            ]
            if agent_result:
                context_parts.append(
                    "Agent flow log (excerpt):\n" + agent_result.flow_log[:5000]
                )
            context = "\n\n".join(context_parts)
            judge_results = await self.judge.evaluate(context, step.llm_criteria)

        return VerifyStepResult(
            step=step,
            tool_output=tool_output,
            assertion_results=assertion_results,
            judge_results=judge_results,
        )

    async def run_conversation(
        self,
        scenario: ConversationScenario,
    ) -> ConversationResult:
        """Execute a complete multi-turn conversation."""
        t0 = time.monotonic()
        loop = asyncio.get_event_loop()

        # 1. Run seed commands
        seed_outputs: list[dict[str, Any]] = []
        if scenario.seed_commands:
            seed_outputs = await loop.run_in_executor(
                None,
                self.tool_runner.run_sequence,
                scenario.seed_commands,
            )

        # 2. Run messages sequentially
        message_results: list[MessageResult] = []
        for msg in scenario.messages:
            agent_path, prompt = self._resolve_agent(msg, scenario)

            # Run agent (blocking → executor)
            agent_result = await loop.run_in_executor(
                None,
                self._run_agent,
                agent_path,
                prompt,
                msg.timeout,
            )

            # Run verify steps for this message
            verify_results: list[VerifyStepResult] = []
            for step in msg.verify_steps:
                vr = await self._run_verify_step(step, agent_result)
                verify_results.append(vr)

            # Per-message LLM criteria
            judge_results: list[JudgeResult] = []
            if msg.llm_criteria:
                judge_results = await self.judge.evaluate_flow(
                    agent_result.flow_log,
                    msg.llm_criteria,
                )

            message_results.append(
                MessageResult(
                    message=msg,
                    agent_path=agent_path,
                    agent_result=agent_result,
                    verify_results=verify_results,
                    judge_results=judge_results,
                )
            )

        # 3. Run final verify steps
        final_verify_results: list[VerifyStepResult] = []
        last_agent_result = (
            message_results[-1].agent_result if message_results else None
        )
        for step in scenario.final_verify_steps:
            vr = await self._run_verify_step(step, last_agent_result)
            final_verify_results.append(vr)

        # 4. Flow-level LLM evaluation on combined log
        flow_judge_results: list[JudgeResult] = []
        result = ConversationResult(
            scenario=scenario,
            seed_outputs=seed_outputs,
            message_results=message_results,
            final_verify_results=final_verify_results,
            duration_seconds=0.0,
        )
        if scenario.flow_llm_criteria:
            flow_judge_results = await self.judge.evaluate_flow(
                result.combined_flow_log,
                scenario.flow_llm_criteria,
            )

        elapsed = time.monotonic() - t0
        return ConversationResult(
            scenario=scenario,
            seed_outputs=seed_outputs,
            message_results=message_results,
            final_verify_results=final_verify_results,
            flow_judge_results=flow_judge_results,
            duration_seconds=elapsed,
        )
