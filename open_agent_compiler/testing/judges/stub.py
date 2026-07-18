"""StubJudge — deterministic JudgeClient for tests.

Either accept a {criteria: {pass, score, reasoning}} mapping for keyed
responses, OR accept a default response that applies to every call.
"""

from __future__ import annotations

from typing import Any


class StubJudge:
    """Deterministic JudgeClient impl. Use in tests so no LLM is called."""

    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        default: dict | None = None,
    ) -> None:
        self.responses = responses or {}
        self.default = default or {"pass": True, "score": 1.0, "reasoning": "stub"}
        self.calls: list[dict] = []

    def judge(
        self, criteria: str, target: Any, *, model: str | None = None,
    ) -> dict:
        self.calls.append({"criteria": criteria, "target": target, "model": model})
        if criteria in self.responses:
            return self.responses[criteria]
        return self.default
