"""LLM-based evaluation via vLLM API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_agent_compiler.testing.scenario import LLMCriterion

SYSTEM_PROMPT = """\
You are a test evaluator. Given context and criteria, \
evaluate whether each criterion is met.

Respond with valid JSON: a list of objects, one per criterion, each with:
- "criterion": the criterion description (string)
- "passed": whether it was met (boolean)
- "confidence": your confidence 0.0-1.0 (float)
- "reasoning": brief explanation (string)
"""

FLOW_SYSTEM_PROMPT = """\
You are an agent flow evaluator. Given the full stdout/stderr \
log of an AI agent run, \
evaluate whether each criterion about the agent's behavior is met.

Respond with valid JSON: a list of objects, one per criterion, each with:
- "criterion": the criterion description (string)
- "passed": whether it was met (boolean)
- "confidence": your confidence 0.0-1.0 (float)
- "reasoning": brief explanation (string)
"""


@dataclass
class JudgeResult:
    criterion: str
    passed: bool
    confidence: float
    reasoning: str


class LLMJudge:
    def __init__(
        self,
        base_url: str = "http://192.168.0.95:5502/v1",
        model: str = "qwen-coder-next",
        api_key: str = "EMPTY",
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key

    async def evaluate(
        self,
        context: str,
        criteria: list[LLMCriterion],
    ) -> list[JudgeResult]:
        """Ask LLM to evaluate context against each criterion."""
        prompt = self._build_eval_prompt(context, criteria)
        response = await self._call_api(SYSTEM_PROMPT, prompt)
        return self._parse_results(response, criteria)

    async def evaluate_flow(
        self,
        flow_log: str,
        criteria: list[LLMCriterion],
    ) -> list[JudgeResult]:
        """Evaluate full agent flow log against criteria."""
        prompt = self._build_flow_eval_prompt(flow_log, criteria)
        response = await self._call_api(FLOW_SYSTEM_PROMPT, prompt)
        return self._parse_results(response, criteria)

    def _build_eval_prompt(
        self,
        context: str,
        criteria: list[LLMCriterion],
    ) -> str:
        criteria_text = "\n".join(f"- {c.description}" for c in criteria)
        return f"## Context\n\n{context}\n\n## Criteria to evaluate\n\n{criteria_text}"

    def _build_flow_eval_prompt(
        self,
        flow_log: str,
        criteria: list[LLMCriterion],
    ) -> str:
        criteria_text = "\n".join(f"- {c.description}" for c in criteria)
        # Truncate very long flow logs to avoid token limits
        if len(flow_log) > 30000:
            flow_log = (
                flow_log[:15000] + "\n\n... [truncated] ...\n\n" + flow_log[-15000:]
            )
        return (
            f"## Agent Flow Log\n\n{flow_log}\n\n"
            f"## Criteria to evaluate\n\n{criteria_text}"
        )

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        import httpx  # type: ignore[import-not-found]

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content: str = data["choices"][0]["message"]["content"]
            return content

    @staticmethod
    def _try_repair_json(text: str) -> list[dict[str, object]] | None:
        """Attempt to recover truncated JSON arrays."""
        import re as _re

        # Try closing truncated JSON array: find last complete object
        if text.startswith("["):
            # Find all complete {...} blocks
            objs: list[dict[str, object]] = []
            for m in _re.finditer(r"\{[^{}]*\}", text):
                try:
                    objs.append(json.loads(m.group()))
                except json.JSONDecodeError:
                    continue
            if objs:
                return objs
        # Single truncated object
        if text.startswith("{"):
            # Try adding closing brace
            for suffix in ("}", '"}', '"]}'):
                try:
                    return [json.loads(text + suffix)]
                except json.JSONDecodeError:
                    continue
        return None

    def _parse_results(
        self,
        response: str,
        criteria: list[LLMCriterion],
    ) -> list[JudgeResult]:
        """Parse LLM JSON response into JudgeResult list."""
        # Strip markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            items = self._try_repair_json(text)
            if items is None:
                return [
                    JudgeResult(
                        criterion=c.description,
                        passed=False,
                        confidence=0.0,
                        reasoning=(f"Failed to parse LLM response: {response[:200]}"),
                    )
                    for c in criteria
                ]

        results = []
        for i, criterion in enumerate(criteria):
            if i < len(items):
                item = items[i]
                passed = bool(item.get("passed", False))
                confidence = float(item.get("confidence", 0.0))
                # Apply threshold
                if confidence < criterion.passing_threshold:
                    passed = False
                results.append(
                    JudgeResult(
                        criterion=criterion.description,
                        passed=passed,
                        confidence=confidence,
                        reasoning=item.get("reasoning", ""),
                    )
                )
            else:
                results.append(
                    JudgeResult(
                        criterion=criterion.description,
                        passed=False,
                        confidence=0.0,
                        reasoning=("No evaluation returned for this criterion"),
                    )
                )
        return results
