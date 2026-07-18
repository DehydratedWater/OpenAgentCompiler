"""Deterministic mutators — no LLM, no randomness, just rewriting rules.

Use for: regression-check candidates (identity), prompt-nudge sweeps
(prefix/suffix), sampling-config exploration (temperature). Cheap to
run and produce reproducible variants for the Pareto frontier.
"""

from __future__ import annotations

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.version import ComponentVersion


class IdentityMutator(Mutator):
    """Returns the input version unchanged. Useful as a control."""

    name = "identity"

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        return ComponentVersion.of(
            component_id=version.component_id,
            kind=version.kind,
            definition=version.definition,
            parent_hash=version.content_hash,
            author=self.name,
        )


class PromptPrefixMutator(Mutator):
    """Prepends a fixed string to system_prompt (agent kind only)."""

    name = "prompt-prefix"

    def __init__(self, prefix: str, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self.prefix = prefix

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        current = defn.get("system_prompt", "")
        if self.prefix in current:
            return None  # already applied — don't churn
        defn["system_prompt"] = f"{self.prefix}\n\n{current}".strip()
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=f"{self.name}:{self.prefix[:20]}",
        )


class PromptSuffixMutator(Mutator):
    """Appends a fixed string to system_prompt (agent kind only)."""

    name = "prompt-suffix"

    def __init__(self, suffix: str, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self.suffix = suffix

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        current = defn.get("system_prompt", "")
        if self.suffix in current:
            return None
        defn["system_prompt"] = f"{current}\n\n{self.suffix}".strip()
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=f"{self.name}:{self.suffix[:20]}",
        )


class ToolDescriptionAppendMutator(Mutator):
    """Append a clarifier sentence to a tool's `description` field.

    Operates on `kind="tool"` ComponentVersions whose definition dict
    follows the ToolDefinitionHeader shape — i.e. carries a string
    `description` field. The candidate version becomes
    `description = <baseline>\\n<suffix>`.

    Use to drive an `oac improve` loop that tunes a tool's description
    to match how a particular model prefers tool docs to be phrased.
    Pair with `apply_promoted_to_tool` (Phase 10) to load the winner
    back into the registry on the next compile.
    """

    name = "tool-description-append"

    def __init__(self, suffix: str, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self.suffix = suffix

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "tool":
            return None
        defn = dict(version.definition)
        current = defn.get("description", "")
        if self.suffix in current:
            return None  # already applied — avoid churn
        defn["description"] = (
            f"{current}\n{self.suffix}".strip() if current else self.suffix
        )
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=f"{self.name}:{self.suffix[:20]}",
        )


class ToolRuleAddMutator(Mutator):
    """Append a rule entry to a tool's `rules` list.

    Tools accumulate behavioural rules (`tool.header.rules`) that the
    SECURITY POLICY block emits into the agent's system prompt. This
    mutator adds one rule to the list when not already present.
    Operates on `kind="tool"` ComponentVersions.
    """

    name = "tool-rule-add"

    def __init__(self, rule: str, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self.rule = rule

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "tool":
            return None
        defn = dict(version.definition)
        rules = list(defn.get("rules") or [])
        if self.rule in rules:
            return None
        rules.append(self.rule)
        defn["rules"] = rules
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=f"{self.name}:{self.rule[:20]}",
        )


class ToolFormatMutator(Mutator):
    """Set the agent's `default_tool_format` to a specific value.

    Used to compile-and-compare bash vs json vs both variants of the
    same agent — a typical optimisation when the user isn't sure
    which form a model handles best. Each instance produces ONE
    target form; register three to evaluate all three side by side.

    Operates on `kind="agent"` ComponentVersions.
    """

    name = "tool-format"

    def __init__(
        self, target_format: str, *, name: str | None = None,
    ) -> None:
        if target_format not in ("bash", "json", "both"):
            raise ValueError(
                f"target_format must be 'bash'/'json'/'both', not {target_format!r}"
            )
        super().__init__(name=name or f"{self.name}:{target_format}")
        self.target_format = target_format

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        if defn.get("default_tool_format") == self.target_format:
            return None
        defn["default_tool_format"] = self.target_format
        return ComponentVersion.of(
            component_id=version.component_id, kind=version.kind,
            definition=defn, parent_hash=version.content_hash,
            author=f"{self.name}:{self.target_format}",
        )


class TemperatureMutator(Mutator):
    """Adjust an agent's temperature within [min_t, max_t]."""

    name = "temperature"

    def __init__(
        self, delta: float, *, min_t: float = 0.0, max_t: float = 1.5,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.delta = delta
        self.min_t = min_t
        self.max_t = max_t

    def mutate(
        self, version: ComponentVersion, ctx: MutationContext,
    ) -> ComponentVersion | None:
        if version.kind != "agent":
            return None
        defn = dict(version.definition)
        # Temperature can live in different shapes depending on how the
        # registry built the definition — check the common paths.
        for key in ("temperature",):
            if key in defn:
                new_t = round(
                    max(self.min_t, min(self.max_t, defn[key] + self.delta)),
                    3,
                )
                if new_t == defn[key]:
                    return None
                defn[key] = new_t
                return ComponentVersion.of(
                    component_id=version.component_id, kind=version.kind,
                    definition=defn, parent_hash=version.content_hash,
                    author=f"{self.name}:{self.delta:+}",
                )
        # Nested model_parameters shape (matches AgentVariant dump).
        params = defn.get("model_parameters")
        if isinstance(params, dict) and "temperature" in params:
            new_t = round(
                max(self.min_t, min(self.max_t, params["temperature"] + self.delta)),
                3,
            )
            if new_t == params["temperature"]:
                return None
            new_params = {**params, "temperature": new_t}
            defn["model_parameters"] = new_params
            return ComponentVersion.of(
                component_id=version.component_id, kind=version.kind,
                definition=defn, parent_hash=version.content_hash,
                author=f"{self.name}:{self.delta:+}",
            )
        return None
