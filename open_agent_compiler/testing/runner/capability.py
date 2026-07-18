"""Capability-test runner: pure introspection over a compiled permission dict.

A CapabilityTest declares assertions about what an agent's compiled
permission YAML must (or must not) contain. The runner expands the
must_have / must_not_have shorthand into PermissionPresent/Absent
evaluators, prepends them to the test's explicit evaluator list, and
runs every check against a RunContext populated with the permissions
dict.

The compiled artifact shape this expects matches what
`compile_permissions.generate_permissions(variant)` returns:

    {
      "permission": {
        "*": "deny",
        "read": "allow" | False,
        "write": ...,
        "bash": {"*": "deny", "uv run scripts/x.py *": "allow"},
        "skill": {"*": "deny", "data-query": "allow"},
        ...
      },
      "tool": { ... mirror used informally ... }
    }
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.test_model import (
    CapabilityTest,
    PermissionAbsentEvaluator,
    PermissionPresentEvaluator,
)
from open_agent_compiler.testing.evaluation import EvaluationResult, RunContext, evaluate


class CapabilityRunResult(BaseModel):
    """Per-test result: a label + list of every evaluator outcome."""

    model_config = ConfigDict(frozen=False)

    test_name: str
    passed: bool
    results: list[EvaluationResult] = Field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skipped)


def _expand_capability_evaluators(test: CapabilityTest):
    """Synthesize PermissionPresent/Absent evaluators from must_* fields."""
    out = []
    for tool in test.must_have_tools:
        out.append(PermissionPresentEvaluator(
            name=f"must_have_tool:{tool}", permission_key=tool,
        ))
    for tool in test.must_not_have_tools:
        out.append(PermissionAbsentEvaluator(
            name=f"must_not_have_tool:{tool}", permission_key=tool,
        ))
    for skill in test.must_have_skills:
        out.append(PermissionPresentEvaluator(
            name=f"must_have_skill:{skill}",
            permission_key="skill",
        ))
        # second pass with the deeper {skill: rule} check would need a
        # different evaluator shape; for now must_have_skill asserts that
        # the skill key is present in permission.skill mapping.
        out.append(_SkillRuleEvaluator(
            name=f"must_have_skill_allow:{skill}", skill_name=skill, must_allow=True,
        ))
    for skill in test.must_not_have_skills:
        out.append(_SkillRuleEvaluator(
            name=f"must_not_have_skill:{skill}", skill_name=skill, must_allow=False,
        ))
    for pattern in test.must_have_bash_patterns:
        out.append(PermissionPresentEvaluator(
            name=f"must_have_bash:{pattern}",
            permission_key="bash", bash_pattern=pattern,
        ))
    for pattern in test.must_not_have_bash_patterns:
        out.append(PermissionAbsentEvaluator(
            name=f"must_not_have_bash:{pattern}",
            permission_key="bash", bash_pattern=pattern,
        ))
    out.extend(test.evaluators)
    return out


class _SkillRuleEvaluator(PermissionPresentEvaluator):
    """Internal helper: assert permission.skill[<name>] is 'allow' (or absent).

    Subclasses PermissionPresentEvaluator only so it carries the right
    `kind` for the dispatcher and gets the same boilerplate fields.
    """

    skill_name: str
    must_allow: bool = True

    def __init__(self, **data):
        # Force the permission_key for the base class.
        data.setdefault("permission_key", "skill")
        super().__init__(**data)


from open_agent_compiler.testing.evaluation import register  # noqa: E402


@register("permission_present")  # type: ignore[no-redef]
def _permission_present_with_skill_branch(ev, ctx):  # noqa: D401, ANN001
    """Override the dispatcher entry for permission_present to handle skill rules.

    Re-using the dispatcher slot means custom skill_rule logic lives in one
    place. The base permission_present check still runs for non-skill cases.
    """
    if isinstance(ev, _SkillRuleEvaluator):
        if ctx.permissions is None:
            return EvaluationResult.skip(ev, "RunContext.permissions is None")
        skills = ctx.permissions.get("skill")
        if not isinstance(skills, dict):
            present_allow = False
        else:
            value = skills.get(ev.skill_name)
            present_allow = value == "allow"
        passed = present_allow if ev.must_allow else not present_allow
        return EvaluationResult.from_check(
            ev, passed,
            evidence=(
                f"skill[{ev.skill_name!r}] allow={present_allow}"
                f" (need allow={ev.must_allow})"
            ),
            details={"present_allow": present_allow, "must_allow": ev.must_allow},
        )
    # Fall through to the standard permission_present implementation.
    from open_agent_compiler.testing.evaluators.deterministic import _permission_present

    return _permission_present(ev, ctx)


def run_capability_test(
    test: CapabilityTest,
    permissions: dict,
    *,
    declared_tools: tuple[str, ...] = (),
) -> CapabilityRunResult:
    """Run one CapabilityTest against a compiled permission dict.

    `declared_tools` are the agent's tool names (extra_tools + workflow
    tools_used). A custom/bash tool registers a bash command, not a permission
    key named after the tool, so `must_have_tools=("emit-guidance",)` would
    otherwise never resolve. We treat each declared tool name as present for the
    must_have_tools / must_not_have_tools check by overlaying it onto the
    permission dict used for evaluation only — the compiled artifact is
    untouched.
    """
    eval_perms = permissions
    if declared_tools:
        eval_perms = {**permissions, **{t: "allow" for t in declared_tools}}
    evaluators = _expand_capability_evaluators(test)
    ctx = RunContext(permissions=eval_perms)
    results = [evaluate(ev, ctx) for ev in evaluators]
    passed = all(r.passed for r in results)
    return CapabilityRunResult(
        test_name=test.name, passed=passed, results=results,
    )
