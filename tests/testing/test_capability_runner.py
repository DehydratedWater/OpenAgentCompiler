"""CapabilityRunner: introspect compiled permissions against a CapabilityTest."""

from __future__ import annotations

from open_agent_compiler.model.core.test_model import (
    CapabilityTest,
    PermissionAbsentEvaluator,
)
from open_agent_compiler.testing.runner.capability import run_capability_test


def _permissions(**overrides) -> dict:
    base = {
        "*": "deny",
        "read": False,
        "write": False,
        "edit": False,
        "task": False,
        "todoread": False,
        "todowrite": False,
        "mcp": False,
        "bash": {"*": "deny"},
        "skill": {"*": "deny"},
    }
    base.update(overrides)
    return base


def test_must_have_tools_passes_when_present() -> None:
    test = CapabilityTest(name="t", must_have_tools=("read",))
    perms = _permissions(read="allow")
    out = run_capability_test(test, perms)
    assert out.passed
    assert out.results[0].passed


def test_must_have_tools_fails_when_denied() -> None:
    test = CapabilityTest(name="t", must_have_tools=("write",))
    out = run_capability_test(test, _permissions())
    assert not out.passed


def test_must_not_have_tools_passes_when_absent() -> None:
    test = CapabilityTest(name="t", must_not_have_tools=("write",))
    out = run_capability_test(test, _permissions())
    assert out.passed


def test_must_not_have_tools_fails_when_allow() -> None:
    test = CapabilityTest(name="t", must_not_have_tools=("write",))
    out = run_capability_test(test, _permissions(write="allow"))
    assert not out.passed


def test_must_have_skills_requires_allow_value() -> None:
    test = CapabilityTest(name="t", must_have_skills=("data-query",))
    perms = _permissions()
    perms["skill"] = {"*": "deny", "data-query": "allow"}
    out = run_capability_test(test, perms)
    assert out.passed


def test_must_have_skills_fails_when_not_allow() -> None:
    test = CapabilityTest(name="t", must_have_skills=("data-query",))
    perms = _permissions()
    perms["skill"] = {"*": "deny"}
    out = run_capability_test(test, perms)
    assert not out.passed


def test_must_not_have_skills_passes_when_denied() -> None:
    test = CapabilityTest(name="t", must_not_have_skills=("dangerous-skill",))
    perms = _permissions()
    perms["skill"] = {"*": "deny", "data-query": "allow"}
    out = run_capability_test(test, perms)
    assert out.passed


def test_must_have_bash_patterns_passes_when_listed() -> None:
    test = CapabilityTest(
        name="t",
        must_have_bash_patterns=("uv run scripts/safe.py *",),
    )
    perms = _permissions()
    perms["bash"] = {"*": "deny", "uv run scripts/safe.py *": "allow"}
    out = run_capability_test(test, perms)
    assert out.passed


def test_must_not_have_bash_patterns_passes_when_absent() -> None:
    test = CapabilityTest(
        name="t",
        must_not_have_bash_patterns=("rm -rf *",),
    )
    out = run_capability_test(test, _permissions())
    assert out.passed


def test_explicit_evaluators_run_alongside_must_haves() -> None:
    test = CapabilityTest(
        name="t",
        must_have_tools=("read",),
        evaluators=(
            PermissionAbsentEvaluator(permission_key="write"),
        ),
    )
    out = run_capability_test(test, _permissions(read="allow"))
    assert out.passed
    # 1 must_have synthesis + 1 explicit = 2 results
    assert len(out.results) == 2


def test_one_failure_fails_overall_test() -> None:
    test = CapabilityTest(
        name="t",
        must_have_tools=("read", "write"),  # only read is allowed
    )
    out = run_capability_test(test, _permissions(read="allow"))
    assert not out.passed
    assert out.failed_count == 1


def test_skipped_results_do_not_count_as_failures() -> None:
    # An llm_judge inside a capability test would skip without a judge;
    # the runner should still consider the overall test passed if other
    # checks pass.
    from open_agent_compiler.model.core.test_model import LLMJudgeEvaluator

    test = CapabilityTest(
        name="t",
        must_have_tools=("read",),
        evaluators=(LLMJudgeEvaluator(criteria="anything"),),
    )
    out = run_capability_test(test, _permissions(read="allow"))
    # llm_judge skipped → passed=True with skipped=True in EvaluationResult,
    # so all(r.passed) is True overall.
    assert out.passed
    skipped = [r for r in out.results if r.skipped]
    assert len(skipped) == 1


def test_declared_tools_resolve_must_have_for_custom_bash_tools() -> None:
    # A custom bash tool registers a bash command, not a permission key named
    # after the tool. `declared_tools` lets must_have_tools resolve such tools
    # without touching the compiled artifact.
    test = CapabilityTest(
        name="t",
        must_have_tools=("emit-guidance",),
        must_not_have_tools=("write", "edit"),
    )
    perms = _permissions(write=False, edit=False)
    # Without declaring the tool, the positive check can't see it → fails.
    assert not run_capability_test(test, perms).passed
    # Declaring it (as the agent's extra_tools would) → passes.
    out = run_capability_test(test, perms, declared_tools=("emit-guidance",))
    assert out.passed
