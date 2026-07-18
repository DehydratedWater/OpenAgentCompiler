"""ImprovementAgent — a framework-compiled agent that proposes mutations.

The framework can be applied to itself: build an AgentDefinition whose
job is to read JSONL test artifacts, classify failures, and emit a
JSON mutation proposal for the target component. Run it through the
same compile → opencode → response pipeline as any user agent.

This module ships:

1. `build_improvement_agent_definition(target, criterion)` —
   returns an AgentDefinition with system prompt + workflow shaped for
   the improvement task. Drop into your registry alongside your other
   agents.

2. `ImprovementAgentMutator(invoker, target)` — a Mutator that calls
   the configured invoker (a callable taking prompt → JSON response)
   to get a proposal and turn it into a candidate ComponentVersion.

The invoker is user-supplied because how an agent runs is
deployment-specific. Typical impl: POST to <FASTAPI_URL>/agents/
improvement/run with the prompt and parse the returned stdout for
JSON. The scaffolded FastAPI service from `oac init` exposes the
right endpoint.

ImprovementAgentMutator is what hooks the framework-compiled agent
into Phase 6.5's IterativeLoop — replacing or augmenting the bundled
LLMPromptRewriter with a full framework-driven optimisation flow.
"""

from __future__ import annotations

import json
from typing import Callable

from open_agent_compiler.improvement.criteria import OptimisationCriterion
from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion
from open_agent_compiler.model.core.agent_model import AgentDefinition, AgentHeader
from open_agent_compiler.model.core.workflow_model import (
    Criterion,
    WorkflowStepDefinition,
)


_SYSTEM_PROMPT_TEMPLATE = """\
You are an Improvement Agent for {target!r}.

Your job: read the JSONL test artifacts produced by `oac test` for the
target component, identify the specific evaluator failures, and propose
ONE minimal mutation that would address the highest-priority failure.

Optimisation criterion: {criterion_name}
Aggregation: {aggregation}

Constraints:
- Never recommend removing capabilities the agent already has.
- Never propose mutations to multiple components in one response.
- Prefer the smallest change that addresses the failure (one prompt
  edit, one tool description tweak, one sampling adjustment).
- Output ONLY a single JSON object with no surrounding prose.

Response schema:
{{
  "mutation_kind": "system_prompt" | "tool_description" | "temperature"
                   | "subagent_inject" | "other",
  "rationale": "one sentence",
  "patch": {{
    // for system_prompt mutations: {{ "new_value": "..." }}
    // for tool_description: {{ "tool_name": "...", "new_value": "..." }}
    // for temperature: {{ "new_value": 0.5 }}
    // for subagent_inject: {{ "subagent_name": "...", "reason": "..." }}
  }}
}}
"""


def build_improvement_agent_definition(
    *, target: str, criterion: OptimisationCriterion,
    name: str = "oac/improvement-agent",
) -> AgentDefinition:
    """An AgentDefinition the user can register + compile + invoke."""
    return AgentDefinition(
        header=AgentHeader(
            agent_id=name,
            name=name,
            description=(
                "Reads JSONL test artifacts and proposes one minimal"
                " mutation for the target component."
            ),
        ),
        usage_explanation_long=(
            "Operates on the artifacts under .oac/test_results.jsonl"
            " emitted by `oac test`. Returns a single JSON object with"
            " the proposed mutation; the IterativeLoop wraps that as a"
            " ComponentVersion via ImprovementAgentMutator."
        ),
        usage_explanation_short="proposes a mutation for the target component",
        system_prompt=_SYSTEM_PROMPT_TEMPLATE.format(
            target=target,
            criterion_name=criterion.name,
            aggregation=criterion.aggregation,
        ),
        workflow=[
            WorkflowStepDefinition(
                id=1,
                name="ReadArtifacts",
                instructions=(
                    "Load .oac/test_results.jsonl. Group entries by"
                    " test_name and keep only the most recent run per"
                    " composite_hash."
                ),
            ),
            WorkflowStepDefinition(
                id=2,
                name="ClassifyFailures",
                instructions=(
                    "Identify the top failure category: which evaluator"
                    " kind regressed most? Which test names appear most"
                    " often? Set local var `top_failure_kind`."
                ),
                evaluates=(
                    Criterion(
                        name="top_failure_kind",
                        question="Which kind of evaluator regressed most?",
                        possible_values=(
                            "equals", "substring", "regex", "json_path",
                            "tool_called", "tool_not_called",
                            "permission_present", "permission_absent",
                            "llm_judge",
                        ),
                    ),
                ),
            ),
            WorkflowStepDefinition(
                id=3,
                name="ProposeMutation",
                instructions=(
                    "Pick the smallest mutation that would resolve the top"
                    " failure. Emit ONE JSON object matching the response"
                    " schema in the system prompt. Do NOT include prose."
                ),
            ),
        ],
        todo_mode="lazy",
    )


# ----- Mutator wrapper -------------------------------------------------


Invoker = Callable[[str], str]
"""A callable that takes a prompt string and returns the agent's stdout."""


def _coerce_patch_to_definition(
    base_definition: dict, kind: str, patch: dict,
) -> dict | None:
    """Apply a mutation patch to a copy of the base definition.

    Returns None when the patch doesn't make sense for this base
    definition (so the caller can skip without crashing).
    """
    defn = dict(base_definition)
    if kind == "system_prompt":
        new_value = patch.get("new_value")
        if not isinstance(new_value, str) or not new_value.strip():
            return None
        defn["system_prompt"] = new_value
        return defn
    if kind == "temperature":
        new_value = patch.get("new_value")
        if not isinstance(new_value, (int, float)):
            return None
        # Look in both common shapes (mirrors TemperatureMutator).
        if "temperature" in defn:
            defn["temperature"] = float(new_value)
            return defn
        params = defn.get("model_parameters")
        if isinstance(params, dict) and "temperature" in params:
            defn["model_parameters"] = {**params, "temperature": float(new_value)}
            return defn
        return None
    if kind == "tool_description":
        # Tool description mutations apply to a referenced tool, not the
        # agent definition itself. When the loop is iterating on a tool
        # ComponentVersion (kind='tool'), use ToolDescriptionAppendMutator
        # (deterministic) or build a tool-aware LLM mutator. The agent
        # path here is intentionally a no-op so the loop falls through
        # to the next mutator without crashing.
        return None
    if kind == "subagent_inject":
        sa_name = patch.get("subagent_name")
        if not isinstance(sa_name, str):
            return None
        existing = list(defn.get("subagents", []))
        if any(sa.get("name") == sa_name for sa in existing):
            return None  # already present
        existing.append({"name": sa_name, "description": patch.get("reason", "")})
        defn["subagents"] = existing
        return defn
    return None


class ImprovementAgentMutator(Mutator):
    """Mutator that delegates to the framework-compiled ImprovementAgent.

    Args:
        invoker: callable taking a prompt string + returning the agent's
            stdout (the agent emits a JSON mutation per the schema in
            its system prompt).
        prompt_template: format string with one {failures} slot. Defaults
            to a compact serialisation of MutationContext.failures.
    """

    name = "improvement-agent"

    def __init__(
        self, invoker: Invoker, *,
        prompt_template: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.invoker = invoker
        self.prompt_template = prompt_template or (
            "Failures observed:\n{failures}\n\n"
            "Emit the JSON mutation per the response schema."
        )

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        prompt = self.prompt_template.format(
            failures=json.dumps(ctx.failures, indent=2, default=str),
        )
        try:
            raw = self.invoker(prompt)
        except Exception:  # noqa: BLE001 - same philosophy as LLMPromptRewriter
            return None
        try:
            response = json.loads(raw.strip())
        except json.JSONDecodeError:
            return None
        kind = response.get("mutation_kind")
        patch = response.get("patch")
        if not isinstance(kind, str) or not isinstance(patch, dict):
            return None
        new_defn = _coerce_patch_to_definition(version.definition, kind, patch)
        if new_defn is None:
            return None
        return ComponentVersion.of(
            component_id=version.component_id,
            kind=version.kind,
            definition=new_defn,
            parent_hash=version.content_hash,
            author=f"{self.name}:{kind}",
            notes=response.get("rationale", ""),
        )
