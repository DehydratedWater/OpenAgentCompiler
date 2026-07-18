"""LLM-backed mutators. Imports stay lazy so anthropic/openai are optional."""

from __future__ import annotations

from typing import Any, Protocol

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion


class LLMMutatorClient(Protocol):
    """Pluggable LLM client for prompt rewriters and similar mutators.

    Returns the raw rewritten text. The mutator wraps that into a new
    ComponentVersion. Implementations are decoupled from any specific
    SDK; pass anthropic / openai / a stub instance from tests.
    """

    def rewrite(
        self,
        target: str,
        guidance: str,
        *,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """Return the rewritten target text."""
        ...


class _StubLLM:
    """Minimal in-test client. Records calls; returns canned text."""

    def __init__(self, response: str = "REWRITTEN") -> None:
        self.response = response
        self.calls: list[dict] = []

    def rewrite(
        self, target: str, guidance: str, *,
        context: dict[str, Any] | None = None, model: str | None = None,
    ) -> str:
        self.calls.append({
            "target": target, "guidance": guidance,
            "context": context, "model": model,
        })
        return self.response


_DEFAULT_GUIDANCE = (
    "Rewrite the agent's system prompt to address the failures listed in"
    " context.failures. Keep it concise. Do NOT add unrelated capabilities."
    " Preserve the agent's overall persona and tone."
)


class LLMPromptRewriter(Mutator):
    """Asks the configured LLM to rewrite an agent's system_prompt.

    Skips (returns None) when:
    - the version is not an agent
    - no llm client is on the MutationContext
    - the agent has no system_prompt to rewrite
    """

    name = "llm-prompt-rewriter"

    def __init__(
        self, *,
        guidance: str | None = None,
        model: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.guidance = guidance or _DEFAULT_GUIDANCE
        self.model = model

    @staticmethod
    def _extract_contract_hints(version: ComponentVersion) -> dict[str, Any]:
        """Pull the I/O-contract-like fields a rewriter must preserve.

        These are the fields whose semantics callers depend on — output
        schema, tool names, required commands. The LLM uses them as
        guardrails so a rewrite improving phrasing doesn't accidentally
        change the agent's output scale or tool surface.
        """
        defn = version.definition or {}
        hints: dict[str, Any] = {
            "agent_id": defn.get("name") or defn.get("agent_id"),
        }
        for key in (
            "default_tool_format", "todo_mode", "workspace",
            "model_class",
        ):
            if key in defn:
                hints[key] = defn[key]
        skills = defn.get("skills")
        if isinstance(skills, list):
            hints["skills"] = [
                s.get("name") for s in skills
                if isinstance(s, dict) and "name" in s
            ]
        subagents = defn.get("subagents")
        if isinstance(subagents, list):
            hints["subagents"] = [
                sa.get("name") for sa in subagents
                if isinstance(sa, dict) and "name" in sa
            ]
        extra_tools = defn.get("extra_tools")
        if isinstance(extra_tools, list):
            tool_names = []
            for t in extra_tools:
                if not isinstance(t, dict):
                    continue
                header = t.get("header", {})
                if isinstance(header, dict) and "name" in header:
                    tool_names.append(header["name"])
            hints["tools"] = tool_names
        return hints

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        if ctx.llm is None:
            return None
        defn = dict(version.definition)
        current = defn.get("system_prompt", "")
        if not current:
            return None
        # Propagate the criterion + contract hints to the LLM so the
        # rewrite stays on-target. Without this, the LLM is free to
        # invent new output formats / scales / fields and the criterion
        # can detect the regression but not prevent it.
        criterion_dict = (
            ctx.criterion.model_dump()
            if getattr(ctx, "criterion", None) is not None
            else None
        )
        contract_hints = self._extract_contract_hints(version)
        try:
            rewritten = ctx.llm.rewrite(
                target=current,
                guidance=self.guidance,
                context={
                    "failures": ctx.failures,
                    "criterion": criterion_dict,
                    "contract": contract_hints,
                },
                model=self.model,
            )
        except Exception:  # noqa: BLE001 - degrade gracefully
            return None
        if not rewritten or rewritten == current:
            return None
        defn["system_prompt"] = rewritten
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=self.name,
        )
