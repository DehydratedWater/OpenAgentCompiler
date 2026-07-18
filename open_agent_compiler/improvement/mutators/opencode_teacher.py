"""Teacher-via-opencode: the canonical strong-model client for the autoloop.

The autoloop's teacher (prompt rewriter + judge + probe writer) is a STRONG
model — typically GLM via z.ai's coding plan. That plan is licensed for use
**through opencode**; hammering the provider's raw `…/chat/completions`
endpoint directly risks an account ban. Three consumers shipped exactly that
raw-API call because each hand-rolled its teacher. This module makes the
opencode path the canonical, importable teacher so no consumer hand-rolls a
provider call again.

`OpencodeMutatorClient` is a first-class `LLMMutatorClient` (so `LLMPromptRewriter`
can use it) AND exposes `.judge(...)` so the same routed-through-opencode path
scores LLMJudge tests. It runs the teacher as a flat opencode agent on a model
ref like `zai-coding-plan/glm-5.1` — exactly like the student runs on qwen, only
the model differs.

It is built on `OpencodeRunner` (the sync eval runner), so it inherits error
surfacing + the empty-output/`Agent not found` retry. No raw HTTP anywhere.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_agent_compiler.improvement.opencode_eval import OpencodeRunner

# A model ref WITHOUT a provider prefix is assumed to be a z.ai coding-plan
# model and routed through opencode's zai-coding-plan provider.
_DEFAULT_PROVIDER = "zai-coding-plan"
_TEACHER_SYSTEM = (
    "You are a precise assistant. Do exactly what the user's message asks and"
    " return only the requested output — no preamble, no commentary, no tool use.\n"
)


def normalize_model_ref(model: str, *, default_provider: str = _DEFAULT_PROVIDER) -> str:
    """`glm-5.1` -> `zai-coding-plan/glm-5.1`; an already-qualified ref is kept."""
    return model if "/" in model else f"{default_provider}/{model}"


def teacher_agent_name(model_ref: str) -> str:
    """A flat, filesystem-safe agent name for a teacher model.

    Named WITHOUT a `cand_` prefix so a per-run candidate cleanup that globs
    `cand_*.md` never deletes the teacher.
    """
    return "teacher_" + re.sub(r"[^a-zA-Z0-9]", "_", model_ref)


def install_teacher_agent(
    workspace: Path, model_ref: str, *, system: str = _TEACHER_SYSTEM,
) -> str:
    """Write a flat teacher agent `.md` into `<workspace>/.opencode/agents/`.

    Returns the flat agent name. Idempotent: re-writing is harmless.
    """
    agents = workspace / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    name = teacher_agent_name(model_ref)
    (agents / f"{name}.md").write_text(f"---\nmodel: {model_ref}\n---\n{system}")
    return name


def _strip_fences(text: str) -> str:
    return re.sub(r"^```[a-zA-Z0-9]*\n?|\n?```$", "", text.strip())


class OpencodeMutatorClient:
    """`LLMMutatorClient` + judge backed by a teacher model run via opencode.

    Construct with the workspace (an opencode project root holding `opencode.json`)
    and the teacher model ref. `rewrite(...)` returns an improved system prompt;
    `judge(...)` returns `{"pass", "score", "reasoning"}`. Both route through
    opencode — never a raw provider API.

    `runner` defaults to an `OpencodeRunner(build_dir=workspace)`; inject a
    pre-built one (or a fake exposing `.run(...)`) in tests.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        model: str = "glm-5.1",
        default_provider: str = _DEFAULT_PROVIDER,
        runner: OpencodeRunner | None = None,
        timeout_s: float = 180.0,
        pass_threshold: float = 0.7,
        install: bool = True,
    ) -> None:
        self.workspace = Path(workspace)
        self.model_ref = normalize_model_ref(model, default_provider=default_provider)
        self.default_provider = default_provider
        self.runner = runner or OpencodeRunner(build_dir=self.workspace)
        self.timeout_s = timeout_s
        self.pass_threshold = pass_threshold
        self.agent_name = teacher_agent_name(self.model_ref)
        if install:
            install_teacher_agent(self.workspace, self.model_ref)

    # --- low-level: one teacher completion, routed through opencode ----------

    def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        """One teacher completion via opencode. Returns '' on failure/error.

        opencode agents take their system prompt from the compiled `.md`, so the
        system + user messages are folded into a single prompt turn.
        """
        agent_name = self.agent_name
        if model is not None:
            model_ref = normalize_model_ref(model, default_provider=self.default_provider)
            agent_name = install_teacher_agent(self.workspace, model_ref)
        prompt = f"{system}\n\n---\n\n{user}" if system else user
        result = self.runner.run(
            agent_name=agent_name, prompt=prompt, timeout_s=self.timeout_s,
        )
        # OpencodeRunner surfaces error events; a surfaced error means no usable
        # answer — return '' so the caller degrades (keeps the original prompt).
        if result.error:
            return ""
        return result.final_text().strip()

    # --- LLMMutatorClient: the prompt rewriter -------------------------------

    def rewrite(
        self, target: str, guidance: str, *,
        context: dict[str, Any] | None = None, model: str | None = None,
    ) -> str:
        """Propose an improved system prompt from the failing-test evidence.

        The teacher is told the agent will run on a mid-size LOCAL model, so the
        rewrite should be explicit, concrete, and unambiguous. Returns the new
        prompt text, or the original `target` if the teacher gave nothing.
        """
        failures = (context or {}).get("failures") or []
        fail_text = "\n".join(
            f"- {json.dumps(f)[:400]}" for f in failures[:10]
        ) or "(none recorded)"
        system = (
            "You are a senior prompt engineer improving an AI agent's system"
            " prompt. The agent runs on a MID-SIZE LOCAL MODEL, so the prompt must"
            " be explicit, concrete, and unambiguous — spell out the expected"
            " behaviour, output shape, and any required keywords/markers. Given the"
            " current prompt and the checks it FAILED, return an improved prompt"
            " that would pass them. Preserve the agent's persona, tools, and intent;"
            " do NOT invent unrelated capabilities. Return ONLY the new prompt text"
            " — no preamble, no markdown fences, no commentary."
        )
        user = (
            f"GUIDANCE: {guidance}\n\n"
            f"FAILED CHECKS / EVIDENCE (what to fix):\n{fail_text}\n\n"
            f"CURRENT SYSTEM PROMPT:\n{target}\n\n"
            "Return the improved system prompt only."
        )
        text = _strip_fences(self.complete(system, user, model=model))
        return text or target

    # --- judge: score a response against a criterion (routed via opencode) ---

    def judge(self, criteria: str, target: Any, *, model: str | None = None) -> dict:
        """Grade how well RESPONSE satisfies CRITERION, 0..1. Routed via opencode.

        Returns `{"pass": bool, "score": float, "reasoning": str}`.
        """
        system = (
            "You are a strict evaluator. Score how well the RESPONSE satisfies the"
            " CRITERION on a 0.0-1.0 scale (1.0 = fully satisfies, 0.0 = ignores"
            " it). Reward responses that clearly fulfil the agent's role; penalise"
            " refusals, empty/echo replies, off-task rambling, or tool-mechanics"
            " leaking into the answer. Respond with STRICT JSON only:"
            ' {"score": <float 0..1>, "reasoning": "<one sentence>"}'
        )
        user = (
            f"CRITERION:\n{criteria}\n\nRESPONSE:\n{str(target)[:4000]}\n\n"
            "Return the JSON."
        )
        raw = self.complete(system, user, model=model)
        score = 0.0
        reasoning = ""
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                score = float(obj.get("score", 0.0))
                reasoning = str(obj.get("reasoning", ""))[:200]
            except Exception:  # noqa: BLE001
                pass
        score = max(0.0, min(1.0, score))
        return {
            "pass": score >= self.pass_threshold,
            "score": score,
            "reasoning": reasoning,
        }


__all__ = [
    "OpencodeMutatorClient",
    "normalize_model_ref",
    "teacher_agent_name",
    "install_teacher_agent",
]
