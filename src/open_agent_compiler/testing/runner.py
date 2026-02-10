"""Scenario runner — executes complete agent test scenarios."""

from __future__ import annotations

import asyncio
import operator
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

_SUBAGENT_FALLBACK_RE = re.compile(
    r'not found\.\s*Falling back to default|agent ".*" not found',
    re.IGNORECASE,
)

if TYPE_CHECKING:
    from pathlib import Path

    from open_agent_compiler.testing.llm_judge import (
        JudgeResult,
        LLMJudge,
    )
    from open_agent_compiler.testing.scenario import (
        Assertion,
        Scenario,
        VerifyStep,
    )
    from open_agent_compiler.testing.tool_runner import (
        ToolRunner,
    )


@dataclass
class AgentRunResult:
    return_code: int
    stdout: str
    stderr: str
    flow_log: str
    duration_seconds: float = 0.0

    @property
    def subagent_fallback(self) -> bool:
        """Detect if agent fell back because a subagent was invoked."""
        return bool(_SUBAGENT_FALLBACK_RE.search(self.flow_log))


@dataclass
class AssertionResult:
    assertion: Assertion
    actual_value: Any
    passed: bool
    message: str


@dataclass
class VerifyStepResult:
    step: VerifyStep
    tool_output: dict[str, Any]
    assertion_results: list[AssertionResult] = field(
        default_factory=list,
    )
    judge_results: list[JudgeResult] = field(
        default_factory=list,
    )

    @property
    def passed(self) -> bool:
        assertions_ok = all(r.passed for r in self.assertion_results)
        judges_ok = all(r.passed for r in self.judge_results)
        return assertions_ok and judges_ok


@dataclass
class ScenarioResult:
    scenario: Scenario
    seed_outputs: list[dict[str, Any]]
    agent_result: AgentRunResult | None
    verify_results: list[VerifyStepResult]
    flow_judge_results: list[JudgeResult] = field(
        default_factory=list,
    )
    duration_seconds: float = 0.0

    @property
    def all_passed(self) -> bool:
        verify_ok = all(v.passed for v in self.verify_results)
        flow_ok = all(r.passed for r in self.flow_judge_results)
        agent_ok = self.agent_result is not None and self.agent_result.return_code == 0
        no_fallback = (
            self.agent_result is None or not self.agent_result.subagent_fallback
        )
        return verify_ok and flow_ok and agent_ok and no_fallback

    def summary(self) -> str:
        lines = [f"Scenario: {self.scenario.name}"]
        lines.append(f"  Total duration: {self.duration_seconds:.1f}s")

        if self.agent_result:
            lines.append(
                f"  Agent exit code: {self.agent_result.return_code}"
                f" ({self.agent_result.duration_seconds:.1f}s)"
            )
            if self.agent_result.subagent_fallback:
                lines.append(
                    "  [FATAL] Subagent fallback detected — agent"
                    f" '{self.scenario.agent}' is a subagent and cannot"
                    " be invoked directly. Fell back to default agent."
                )

        # Seed summary
        seed_ok = sum(1 for s in self.seed_outputs if s.get("success"))
        seed_fail = len(self.seed_outputs) - seed_ok
        lines.append(f"  Seeds: {seed_ok} ok, {seed_fail} failed")
        for j, so in enumerate(self.seed_outputs):
            ok = "ok" if so.get("success") else "FAIL"
            if j < len(self.scenario.seed_commands):
                cmd = self.scenario.seed_commands[j]
                lines.append(f"    [{ok}] {cmd.script} {cmd.args}")
            else:
                lines.append(f"    [{ok}] (seed {j})")

        for i, vr in enumerate(self.verify_results):
            import json

            status = "PASS" if vr.passed else "FAIL"
            cmd = vr.step.command
            lines.append(f"  Verify step {i + 1}: {status} ({cmd.script} {cmd.args})")
            lines.append("    Tool output:")
            try:
                formatted = json.dumps(
                    vr.tool_output,
                    indent=2,
                    default=str,
                )
                for line in formatted.splitlines():
                    lines.append(f"      {line}")
            except (TypeError, ValueError):
                lines.append(f"      {vr.tool_output!r}")

            for ar in vr.assertion_results:
                s = "PASS" if ar.passed else "FAIL"
                lines.append(
                    f"    [{s}] "
                    f"{ar.assertion.field} "
                    f"{ar.assertion.operator} "
                    f"{ar.assertion.expected}: "
                    f"{ar.message}"
                )
            for jr in vr.judge_results:
                s = "PASS" if jr.passed else "FAIL"
                lines.append(
                    f"    [{s}] LLM: {jr.criterion} "
                    f"(confidence={jr.confidence:.2f})"
                    f": {jr.reasoning}"
                )

        for jr in self.flow_judge_results:
            s = "PASS" if jr.passed else "FAIL"
            lines.append(
                f"  [{s}] Flow LLM: {jr.criterion} "
                f"(confidence={jr.confidence:.2f})"
                f": {jr.reasoning}"
            )

        # On failure, append flow log excerpt
        if not self.all_passed and self.agent_result:
            log = self.agent_result.flow_log
            excerpt = log[-3000:] if len(log) > 3000 else log
            if len(log) > 3000:
                excerpt = "...(truncated)\n" + excerpt
            lines.append("  --- Flow log excerpt ---")
            lines.append(excerpt)

        return "\n".join(lines)


def _resolve_field(data: dict[str, Any], path: str) -> Any:
    """Resolve a dotted/bracketed path into a value."""
    current: Any = data
    for part in path.replace("[", ".[").split("."):
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            idx = int(part[1:-1])
            current = current[idx]
        else:
            current = current[part]
    return current


def _check_assertion(data: dict[str, Any], assertion: Assertion) -> AssertionResult:
    """Evaluate a single assertion against tool output."""
    try:
        actual = _resolve_field(data, assertion.field)
    except (KeyError, IndexError, TypeError) as e:
        return AssertionResult(
            assertion=assertion,
            actual_value=None,
            passed=False,
            message=(f"Field '{assertion.field}' not found: {e}"),
        )

    ops: dict[str, Callable[[Any, Any], bool]] = {
        "eq": operator.eq,
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
        "contains": lambda a, b: b in a,
        "truthy": lambda a, _: bool(a),
        "length_gte": lambda a, b: len(a) >= b,
    }

    op_fn = ops.get(assertion.operator)
    if op_fn is None:
        return AssertionResult(
            assertion=assertion,
            actual_value=actual,
            passed=False,
            message=(f"Unknown operator: {assertion.operator}"),
        )

    passed = op_fn(actual, assertion.expected)
    return AssertionResult(
        assertion=assertion,
        actual_value=actual,
        passed=passed,
        message=(
            f"got {actual!r}"
            if passed
            else (
                f"expected {assertion.operator} {assertion.expected!r}, got {actual!r}"
            )
        ),
    )


class ScenarioRunner:
    def __init__(
        self,
        tool_runner: ToolRunner,
        judge: LLMJudge,
        project_root: Path,
        *,
        attach_url: str | None = None,
    ) -> None:
        self.tool_runner = tool_runner
        self.judge = judge
        self.project_root = project_root
        self.attach_url = attach_url

    async def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Execute a complete scenario."""
        t0 = time.monotonic()
        loop = asyncio.get_event_loop()

        # 1. Run seed commands (blocking I/O → executor)
        seed_outputs = await loop.run_in_executor(
            None,
            self.tool_runner.run_sequence,
            scenario.seed_commands,
        )

        # 2. Run the agent (blocking I/O → executor)
        agent_result = await loop.run_in_executor(
            None,
            self._run_agent,
            scenario,
        )

        # 3. Run verify steps
        verify_results = []
        for step in scenario.verify_steps:
            vr = await self._run_verify_step(step, agent_result)
            verify_results.append(vr)

        # 4. Flow-level LLM evaluation
        flow_judge_results: list[JudgeResult] = []
        if scenario.flow_llm_criteria and agent_result:
            flow_judge_results = await self.judge.evaluate_flow(
                agent_result.flow_log,
                scenario.flow_llm_criteria,
            )

        elapsed = time.monotonic() - t0
        return ScenarioResult(
            scenario=scenario,
            seed_outputs=seed_outputs,
            agent_result=agent_result,
            verify_results=verify_results,
            flow_judge_results=flow_judge_results,
            duration_seconds=elapsed,
        )

    async def run_scenarios(
        self,
        scenarios: list[Scenario],
        *,
        concurrent: bool = False,
    ) -> list[ScenarioResult]:
        """Run multiple scenarios, optionally concurrently.

        When *concurrent* is ``True``, all scenarios are run in parallel
        via ``asyncio.gather`` (each agent subprocess runs in its own
        executor thread).  Exceptions in individual scenarios are caught
        and wrapped in a failed :class:`ScenarioResult`.
        """
        if concurrent:
            return list(await asyncio.gather(*(self._safe_run(s) for s in scenarios)))
        return [await self.run_scenario(s) for s in scenarios]

    async def _safe_run(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario, catching exceptions as failures."""
        try:
            return await self.run_scenario(scenario)
        except Exception as exc:
            return ScenarioResult(
                scenario=scenario,
                seed_outputs=[],
                agent_result=AgentRunResult(
                    return_code=1,
                    stdout="",
                    stderr=str(exc),
                    flow_log=f"Exception during scenario execution: {exc}",
                ),
                verify_results=[],
            )

    def _run_agent(self, scenario: Scenario) -> AgentRunResult:
        """Run agent via opencode CLI."""
        cmd = [
            "opencode",
            "run",
            "--agent",
            scenario.agent,
        ]
        if self.attach_url:
            cmd.extend(["--attach", self.attach_url])
        cmd.append(scenario.agent_prompt)
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                env=self.tool_runner.env,
                timeout=scenario.timeout,
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
            timeout_msg = f"Agent timed out after {scenario.timeout}s"
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
        step: VerifyStep,
        agent_result: AgentRunResult | None,
    ) -> VerifyStepResult:
        """Run a single verification step."""
        # Run the tool command
        tool_output = self.tool_runner.run(step.command)

        # Check programmatic assertions
        assertion_results = [_check_assertion(tool_output, a) for a in step.assertions]

        # Run LLM judge if criteria specified
        judge_results: list[JudgeResult] = []
        if step.llm_criteria:
            import json

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
