"""Deterministic evaluators: equals/substring/regex/json_path/tool_call/permission."""

from __future__ import annotations

import re

from open_agent_compiler.model.core.test_model import (
    EqualsEvaluator,
    JsonPathEvaluator,
    PermissionAbsentEvaluator,
    PermissionPresentEvaluator,
    RegexEvaluator,
    SubstringEvaluator,
    ToolCalledEvaluator,
    ToolNotCalledEvaluator,
)
from open_agent_compiler.testing.evaluation import RunContext, ToolCallRecord, evaluate


# ---- equals --------------------------------------------------------------


def test_equals_whole_target() -> None:
    ev = EqualsEvaluator(expected=42)
    r = evaluate(ev, RunContext(output=42))
    assert r.passed
    assert "actual=42" in r.evidence


def test_equals_dotted_field() -> None:
    ev = EqualsEvaluator(field="tasks.0.status", expected="completed")
    ctx = RunContext(output={"tasks": [{"status": "completed"}]})
    assert evaluate(ev, ctx).passed


def test_equals_dotted_field_missing_fails_cleanly() -> None:
    ev = EqualsEvaluator(field="tasks.5.status", expected="anything")
    r = evaluate(ev, RunContext(output={"tasks": []}))
    assert not r.passed
    assert "not found" in r.evidence


# ---- substring -----------------------------------------------------------


def test_substring_case_sensitive_default() -> None:
    ev = SubstringEvaluator(needle="HELLO")
    r = evaluate(ev, RunContext(output="hello world"))
    assert not r.passed


def test_substring_case_insensitive() -> None:
    ev = SubstringEvaluator(needle="HELLO", case_sensitive=False)
    assert evaluate(ev, RunContext(output="hello world")).passed


def test_substring_against_non_string_coerces() -> None:
    ev = SubstringEvaluator(needle="42")
    r = evaluate(ev, RunContext(output={"answer": 42}))
    assert r.passed


# ---- regex ---------------------------------------------------------------


def test_regex_match() -> None:
    ev = RegexEvaluator(pattern=r"id_\w+")
    assert evaluate(ev, RunContext(output="user id_abc123 logged in")).passed


def test_regex_no_match() -> None:
    ev = RegexEvaluator(pattern=r"\d{10}")
    assert not evaluate(ev, RunContext(output="no digits here")).passed


def test_regex_case_insensitive_flag() -> None:
    ev = RegexEvaluator(pattern=r"hello", flags=re.IGNORECASE)
    assert evaluate(ev, RunContext(output="HELLO world")).passed


# ---- json_path ----------------------------------------------------------


def test_json_path_through_list_index() -> None:
    ev = JsonPathEvaluator(path="tasks.0.id", expected="abc")
    ctx = RunContext(output={"tasks": [{"id": "abc"}, {"id": "def"}]})
    assert evaluate(ev, ctx).passed


def test_json_path_unresolvable() -> None:
    ev = JsonPathEvaluator(path="missing.path", expected="x")
    r = evaluate(ev, RunContext(output={}))
    assert not r.passed
    assert "not resolvable" in r.evidence


def test_json_path_out_of_range_index() -> None:
    ev = JsonPathEvaluator(path="items.99", expected="x")
    r = evaluate(ev, RunContext(output={"items": ["a"]}))
    assert not r.passed


# ---- tool_called / tool_not_called --------------------------------------


def _ctx_with_calls(*calls: dict) -> RunContext:
    return RunContext(tool_calls=[ToolCallRecord(**c) for c in calls])


def test_tool_called_basic() -> None:
    ev = ToolCalledEvaluator(tool_name="search")
    ctx = _ctx_with_calls({"name": "search", "args": {"q": "x"}})
    assert evaluate(ev, ctx).passed


def test_tool_called_min_count() -> None:
    ev = ToolCalledEvaluator(tool_name="search", min_count=2)
    ctx = _ctx_with_calls({"name": "search"}, {"name": "search"})
    assert evaluate(ev, ctx).passed
    ctx2 = _ctx_with_calls({"name": "search"})
    assert not evaluate(ev, ctx2).passed


def test_tool_called_with_args_subset() -> None:
    ev = ToolCalledEvaluator(
        tool_name="search", with_args_subset={"limit": 10},
    )
    ctx = _ctx_with_calls(
        {"name": "search", "args": {"q": "x", "limit": 10}},
    )
    assert evaluate(ev, ctx).passed


def test_tool_called_with_args_subset_mismatch_fails() -> None:
    ev = ToolCalledEvaluator(
        tool_name="search", with_args_subset={"limit": 10},
    )
    ctx = _ctx_with_calls(
        {"name": "search", "args": {"q": "x", "limit": 5}},
    )
    assert not evaluate(ev, ctx).passed


def test_tool_not_called_passes_when_absent() -> None:
    ev = ToolNotCalledEvaluator(tool_name="dangerous")
    assert evaluate(ev, _ctx_with_calls({"name": "safe"})).passed


def test_tool_not_called_fails_when_present() -> None:
    ev = ToolNotCalledEvaluator(tool_name="dangerous")
    assert not evaluate(ev, _ctx_with_calls({"name": "dangerous"})).passed


# ---- permission_present / permission_absent -----------------------------


def test_permission_present_with_allow_string() -> None:
    ev = PermissionPresentEvaluator(permission_key="read")
    ctx = RunContext(permissions={"read": "allow"})
    assert evaluate(ev, ctx).passed


def test_permission_present_with_bool_true() -> None:
    ev = PermissionPresentEvaluator(permission_key="read")
    ctx = RunContext(permissions={"read": True})
    assert evaluate(ev, ctx).passed


def test_permission_present_skipped_when_perms_missing() -> None:
    ev = PermissionPresentEvaluator(permission_key="read")
    r = evaluate(ev, RunContext())
    assert r.skipped
    assert "permissions is None" in r.skip_reason


def test_permission_present_bash_pattern() -> None:
    ev = PermissionPresentEvaluator(
        permission_key="bash", bash_pattern="uv run scripts/safe.py *",
    )
    ctx = RunContext(permissions={
        "bash": {"*": "deny", "uv run scripts/safe.py *": "allow"},
    })
    assert evaluate(ev, ctx).passed


def test_permission_present_bash_pattern_denied() -> None:
    ev = PermissionPresentEvaluator(
        permission_key="bash", bash_pattern="uv run scripts/danger.py *",
    )
    ctx = RunContext(permissions={"bash": {"*": "deny"}})
    assert not evaluate(ev, ctx).passed


def test_permission_absent_passes_when_key_missing() -> None:
    ev = PermissionAbsentEvaluator(permission_key="write")
    assert evaluate(ev, RunContext(permissions={})).passed


def test_permission_absent_fails_when_allow() -> None:
    ev = PermissionAbsentEvaluator(permission_key="write")
    assert not evaluate(ev, RunContext(permissions={"write": "allow"})).passed


def test_permission_absent_bash_pattern() -> None:
    ev = PermissionAbsentEvaluator(
        permission_key="bash", bash_pattern="rm -rf *",
    )
    ctx = RunContext(permissions={"bash": {"*": "deny"}})
    assert evaluate(ev, ctx).passed


# ---- dispatcher skip for unregistered kinds ------------------------------


def test_dispatcher_skips_for_unregistered_kind() -> None:
    # Synthesize an evaluator with a never-registered kind to verify the
    # unknown-kind path. (llm_judge IS registered now in Phase 5.2b; it
    # skips for the different reason of "no judge configured" — covered
    # separately in tests/testing/test_llm_judge.py.)
    from open_agent_compiler.model.core.test_model import EqualsEvaluator

    ev = EqualsEvaluator(expected=1)
    object.__setattr__(ev, "kind", "definitely_not_a_real_kind")
    r = evaluate(ev, RunContext(output=1))
    assert r.skipped
    assert "no implementation" in r.skip_reason
