"""OpenAICompatMutatorClient — a working LLMMutatorClient out of the box.

The LLM-driven mutators (LLMPromptRewriter, TeacherGapRewriter,
LLMWorkflowEditor) speak the small `LLMMutatorClient` protocol. Two
concrete clients now ship:

- `OpencodeMutatorClient` — rewrites through a compiled opencode agent
  (no API keys beyond your opencode auth; slower, battle-tested).
- THIS one — a direct call to any OpenAI-compatible endpoint (OpenAI,
  z.ai, a local vLLM…), reusing the interactive tier's
  `OpenAICompatClient`. Configure explicitly or from env:

      client = OpenAICompatMutatorClient(
          model_id="glm-5.2", base_url="https://api.z.ai/api/coding/paas/v4",
          api_key_env="ZAI_API_KEY",
      )
      # or, in generated scripts / CI:
      client = OpenAICompatMutatorClient.from_env()
      # reads OAC_MUTATOR_MODEL, OAC_MUTATOR_BASE_URL, OAC_MUTATOR_API_KEY
      # (falling back to LIVE_MODEL_ID / LIVE_BASE_URL / LIVE_API_KEY);
      # returns None when no model is configured, so callers can degrade
      # to deterministic mutators instead of crashing.

The rewrite prompt carries the mutator's guidance verbatim plus the
context dict (failures, teacher/student excerpts, contract hints) as
JSON, and the reply is stripped of code fences — the mutators validate
everything downstream anyway (LLMWorkflowEditor rejects malformed
JSON, LLMPromptRewriter rejects empty/unchanged output).
"""

from __future__ import annotations

import json
import os
from typing import Any

from open_agent_compiler.interactive.runner import ChatClient, OpenAICompatClient

_SYSTEM = (
    "You are a precise rewriting engine inside an automated optimization"
    " loop. Follow the guidance exactly. Return ONLY the rewritten"
    " artifact — no preamble, no explanation, no code fences."
)


def _strip_fences(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        lines = out.splitlines()
        out = "\n".join(line for line in lines if not line.startswith("```"))
    return out.strip()


class OpenAICompatMutatorClient:
    """LLMMutatorClient over an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        model_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
        temperature: float = 0.4,
        client: ChatClient | None = None,
    ) -> None:
        self.model_id = model_id
        self.temperature = temperature
        if client is not None:
            self._client: ChatClient = client
        else:
            resolved_key = api_key or (
                os.environ.get(api_key_env, "") if api_key_env else ""
            ) or "not-needed"
            self._client = OpenAICompatClient(
                base_url=base_url, api_key=resolved_key,
            )

    @classmethod
    def from_env(cls) -> "OpenAICompatMutatorClient | None":
        """Build from env (OAC_MUTATOR_* falling back to LIVE_*), or None.

        None — not an error — when no model is configured: loop scripts
        degrade to deterministic mutators instead of failing.
        """
        model_id = os.environ.get("OAC_MUTATOR_MODEL") or os.environ.get(
            "LIVE_MODEL_ID")
        if not model_id:
            return None
        base_url = os.environ.get("OAC_MUTATOR_BASE_URL") or os.environ.get(
            "LIVE_BASE_URL") or None
        api_key = os.environ.get("OAC_MUTATOR_API_KEY") or os.environ.get(
            "LIVE_API_KEY") or None
        return cls(model_id=model_id, base_url=base_url, api_key=api_key)

    def rewrite(
        self,
        target: str,
        guidance: str,
        *,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        user = (
            f"GUIDANCE:\n{guidance}\n\n"
            f"CONTEXT (JSON):\n{json.dumps(context or {}, indent=2, default=str)}\n\n"
            f"ARTIFACT TO REWRITE:\n{target}"
        )
        response = self._client.complete(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            tools=None,
            model=model or self.model_id,
            temperature=self.temperature,
        )
        return _strip_fences(response.content)
