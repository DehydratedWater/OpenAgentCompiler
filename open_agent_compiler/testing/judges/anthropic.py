"""AnthropicJudge — lazy wrapper around the `anthropic` SDK.

The SDK is NOT a runtime dep of open-agent-compiler — it imports lazily
the first time .judge() is called. Consumers who want LLM judges must
install `anthropic` (and any other provider SDK they need) themselves.

The judge prompts the model with a strict JSON-only response contract,
parses it, and returns the {pass, score, reasoning} dict the dispatcher
expects. Malformed responses degrade to a failing judgement instead of
raising, so a flaky judge doesn't crash the whole test run.
"""

from __future__ import annotations

import json
from typing import Any

_JUDGE_PROMPT = (
    "You are evaluating whether an agent/tool output satisfies a criterion.\n"
    "Criterion: {criteria}\n\n"
    "Output to evaluate (may be string, dict, or list):\n"
    "{target}\n\n"
    "Respond with a JSON object ONLY (no prose), with keys:\n"
    '  "pass": boolean — does the output satisfy the criterion?\n'
    '  "score": number in [0,1] — how strongly?\n'
    '  "reasoning": short string — one or two sentences.\n'
)


class AnthropicJudge:
    """JudgeClient backed by Anthropic's Messages API.

    Args:
        model: Default model id (e.g. 'claude-sonnet-4-5-20250929').
        api_key: Optional; falls back to ANTHROPIC_API_KEY env var via SDK.
        max_tokens: Cap on judge response length.
    """

    def __init__(
        self, *,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "AnthropicJudge requires the `anthropic` package."
                " Install it with: uv add anthropic"
            ) from exc
        self._client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        return self._client

    def judge(
        self, criteria: str, target: Any, *, model: str | None = None,
    ) -> dict:
        client = self._ensure_client()
        prompt = _JUDGE_PROMPT.format(
            criteria=criteria,
            target=json.dumps(target, default=str)
            if not isinstance(target, str) else target,
        )
        try:
            response = client.messages.create(
                model=model or self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in response.content
                if getattr(block, "type", None) == "text"
            )
            parsed = _parse_judge_response(text)
        except Exception as exc:  # pragma: no cover - depends on network
            return {
                "pass": False, "score": 0.0,
                "reasoning": f"judge call failed: {exc}",
            }
        return parsed


def _parse_judge_response(text: str) -> dict:
    """Extract a {pass, score, reasoning} dict from the model's response."""
    text = text.strip()
    # Many models wrap JSON in ```json fences; strip them.
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "pass": False, "score": 0.0,
            "reasoning": f"judge returned non-JSON: {text[:200]}",
        }
    return {
        "pass": bool(data.get("pass", False)),
        "score": float(data.get("score", 0.0)),
        "reasoning": str(data.get("reasoning", "")),
    }
