"""Mutators: identity, prompt prefix/suffix, temperature, LLM rewriter."""

from __future__ import annotations

from open_agent_compiler.improvement.mutators import (
    IdentityMutator,
    LLMPromptRewriter,
    MutationContext,
    PromptPrefixMutator,
    PromptSuffixMutator,
    TemperatureMutator,
    ToolDescriptionAppendMutator,
    ToolFormatMutator,
    ToolRuleAddMutator,
)
from open_agent_compiler.improvement.mutators.llm import _StubLLM
from open_agent_compiler.improvement.version import ComponentVersion


def _agent(prompt: str = "be helpful", temperature: float | None = None) -> dict:
    out = {"name": "orch", "system_prompt": prompt, "subagents": []}
    if temperature is not None:
        out["temperature"] = temperature
    return out


def _v(definition: dict | None = None, kind: str = "agent") -> ComponentVersion:
    return ComponentVersion.of(
        component_id="orch", kind=kind, definition=definition or _agent(),
    )


# ---- Identity -----------------------------------------------------------


def test_identity_emits_new_version_with_same_definition() -> None:
    v = _v()
    out = IdentityMutator().mutate(v, MutationContext())
    assert out is not None
    assert out.definition == v.definition
    assert out.parent_hash == v.content_hash
    assert out.author == "identity"


# ---- Prompt prefix / suffix --------------------------------------------


def test_prompt_prefix_prepends() -> None:
    v = _v(_agent("Be polite."))
    out = PromptPrefixMutator("CRITICAL: ").mutate(v, MutationContext())
    assert out is not None
    assert out.definition["system_prompt"].startswith("CRITICAL:")
    assert "Be polite." in out.definition["system_prompt"]
    assert out.parent_hash == v.content_hash


def test_prompt_prefix_skips_when_already_applied() -> None:
    v = _v(_agent("CRITICAL: be polite."))
    assert PromptPrefixMutator("CRITICAL:").mutate(v, MutationContext()) is None


def test_prompt_suffix_appends() -> None:
    v = _v(_agent("Be polite."))
    out = PromptSuffixMutator("Always cite sources.").mutate(v, MutationContext())
    assert out is not None
    assert out.definition["system_prompt"].endswith("Always cite sources.")


def test_prompt_mutators_skip_non_agent_kinds() -> None:
    v = ComponentVersion.of("t", "tool", {"description": "x"})
    assert PromptPrefixMutator("foo").mutate(v, MutationContext()) is None
    assert PromptSuffixMutator("foo").mutate(v, MutationContext()) is None


# ---- Temperature --------------------------------------------------------


def test_temperature_adjusts_top_level_field() -> None:
    v = _v(_agent("hi", temperature=0.5))
    out = TemperatureMutator(+0.2).mutate(v, MutationContext())
    assert out is not None
    assert out.definition["temperature"] == 0.7


def test_temperature_clamps_to_max() -> None:
    v = _v(_agent("hi", temperature=1.4))
    out = TemperatureMutator(+0.5, max_t=1.5).mutate(v, MutationContext())
    assert out is not None
    assert out.definition["temperature"] == 1.5


def test_temperature_skips_when_no_change_after_clamp() -> None:
    v = _v(_agent("hi", temperature=1.5))
    assert TemperatureMutator(+0.1, max_t=1.5).mutate(v, MutationContext()) is None


def test_temperature_handles_nested_model_parameters_shape() -> None:
    defn = {
        "name": "orch",
        "model_parameters": {"model_name": "m", "temperature": 0.3},
    }
    v = ComponentVersion.of("orch", "agent", defn)
    out = TemperatureMutator(-0.1).mutate(v, MutationContext())
    assert out is not None
    assert out.definition["model_parameters"]["temperature"] == 0.2


def test_temperature_returns_none_when_field_absent() -> None:
    v = _v(_agent("hi"))  # no temperature field
    assert TemperatureMutator(+0.1).mutate(v, MutationContext()) is None


# ---- LLM rewriter -------------------------------------------------------


def test_llm_rewriter_skips_when_no_llm_on_context() -> None:
    v = _v(_agent("be polite"))
    assert LLMPromptRewriter().mutate(v, MutationContext()) is None


def test_llm_rewriter_uses_stub_response() -> None:
    llm = _StubLLM(response="be ENORMOUSLY polite")
    v = _v(_agent("be polite"))
    out = LLMPromptRewriter().mutate(v, MutationContext(llm=llm))
    assert out is not None
    assert out.definition["system_prompt"] == "be ENORMOUSLY polite"
    assert out.parent_hash == v.content_hash
    assert llm.calls[0]["target"] == "be polite"


def test_llm_rewriter_skips_when_empty_prompt() -> None:
    llm = _StubLLM(response="x")
    v = _v(_agent(""))
    assert LLMPromptRewriter().mutate(v, MutationContext(llm=llm)) is None


def test_llm_rewriter_skips_when_response_unchanged() -> None:
    llm = _StubLLM(response="same")
    v = _v(_agent("same"))
    assert LLMPromptRewriter().mutate(v, MutationContext(llm=llm)) is None


def test_llm_rewriter_handles_llm_exception_gracefully() -> None:
    class _Boom:
        def rewrite(self, *a, **kw):
            raise RuntimeError("network down")

    v = _v(_agent("hi"))
    assert LLMPromptRewriter().mutate(v, MutationContext(llm=_Boom())) is None


def test_llm_rewriter_passes_failures_through_context() -> None:
    llm = _StubLLM(response="rewritten")
    failures = [{"test_name": "x", "evidence": "y"}]
    v = _v(_agent("original"))
    LLMPromptRewriter().mutate(v, MutationContext(llm=llm, failures=failures))
    assert llm.calls[0]["context"]["failures"] == failures


# ---- Tool mutators (Phase 13) -----------------------------------------


def _tool(description: str = "old desc", rules: list[str] | None = None) -> dict:
    return {
        "name": "echo",
        "description": description,
        "rules": rules or [],
    }


def test_tool_description_append_only_fires_on_tool_kind() -> None:
    """Agent ComponentVersions are not mutated by this tool-targeted mutator."""
    agent_v = _v(_agent("baseline"), kind="agent")
    assert ToolDescriptionAppendMutator("clarifier").mutate(
        agent_v, MutationContext(),
    ) is None


def test_tool_description_append_extends_description() -> None:
    tool_v = _v(_tool("Run the thing."), kind="tool")
    out = ToolDescriptionAppendMutator("Always include units.").mutate(
        tool_v, MutationContext(),
    )
    assert out is not None
    assert out.kind == "tool"
    assert "Run the thing." in out.definition["description"]
    assert "Always include units." in out.definition["description"]


def test_tool_description_append_no_op_when_suffix_already_present() -> None:
    tool_v = _v(_tool("Run.\nAlways include units."), kind="tool")
    assert ToolDescriptionAppendMutator("Always include units.").mutate(
        tool_v, MutationContext(),
    ) is None


def test_tool_rule_add_appends_to_rules_list() -> None:
    tool_v = _v(_tool(rules=["use UTC"]), kind="tool")
    out = ToolRuleAddMutator("never invent values").mutate(
        tool_v, MutationContext(),
    )
    assert out is not None
    assert out.definition["rules"] == ["use UTC", "never invent values"]


def test_tool_rule_add_no_op_when_rule_already_present() -> None:
    tool_v = _v(_tool(rules=["use UTC"]), kind="tool")
    assert ToolRuleAddMutator("use UTC").mutate(
        tool_v, MutationContext(),
    ) is None


def test_tool_rule_add_skips_agent_kinds() -> None:
    agent_v = _v(_agent("baseline"))
    assert ToolRuleAddMutator("rule").mutate(agent_v, MutationContext()) is None


def test_tool_format_sets_default_tool_format() -> None:
    agent_v = _v(_agent("baseline"))
    out = ToolFormatMutator("json").mutate(agent_v, MutationContext())
    assert out is not None
    assert out.definition["default_tool_format"] == "json"


def test_tool_format_no_op_when_format_already_target() -> None:
    defn = _agent("baseline")
    defn["default_tool_format"] = "both"
    v = _v(defn)
    assert ToolFormatMutator("both").mutate(v, MutationContext()) is None


def test_tool_format_rejects_unsupported_target() -> None:
    import pytest
    with pytest.raises(ValueError, match="bash"):
        ToolFormatMutator("xml")


def test_tool_format_skips_tool_kinds() -> None:
    tool_v = _v(_tool(), kind="tool")
    assert ToolFormatMutator("bash").mutate(tool_v, MutationContext()) is None
