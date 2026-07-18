"""Deterministic evaluators — pure, no I/O, no LLM.

Each function takes (evaluator, context) and returns EvaluationResult.
Registered against its `kind` value via @register so the central
dispatcher picks them up.
"""

from __future__ import annotations

import re
from typing import Any

from open_agent_compiler.model.core.test_model import (
    EqualsEvaluator,
    FactRecallEvaluator,
    JsonPathEvaluator,
    PathOrderEvaluator,
    PermissionAbsentEvaluator,
    PermissionPresentEvaluator,
    RegexEvaluator,
    SubstringEvaluator,
    ToolCalledEvaluator,
    ToolNotCalledEvaluator,
)
from open_agent_compiler.testing.evaluation import EvaluationResult, RunContext, register


def _resolve_dotted(target: Any, path: str) -> tuple[bool, Any]:
    """Walk a dotted path (e.g. 'tasks.0.id') through dicts and lists.

    Returns (found, value). Integer-looking segments index lists.
    """
    cursor: Any = target
    for seg in path.split("."):
        if isinstance(cursor, dict):
            if seg in cursor:
                cursor = cursor[seg]
                continue
            return False, None
        if isinstance(cursor, list):
            try:
                idx = int(seg)
            except ValueError:
                return False, None
            if 0 <= idx < len(cursor):
                cursor = cursor[idx]
                continue
            return False, None
        return False, None
    return True, cursor


# ------------- output-shape evaluators -----------------------------------


@register("equals")
def _equals(ev: EqualsEvaluator, ctx: RunContext) -> EvaluationResult:
    if ev.field:
        found, actual = _resolve_dotted(ctx.output, ev.field)
        if not found:
            return EvaluationResult.from_check(
                ev, False,
                evidence=f"field {ev.field!r} not found in output",
                details={"actual": None, "expected": ev.expected},
            )
    else:
        actual = ctx.output
    passed = actual == ev.expected
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"equals: actual={actual!r} expected={ev.expected!r}",
        details={"actual": actual, "expected": ev.expected},
    )


@register("substring")
def _substring(ev: SubstringEvaluator, ctx: RunContext) -> EvaluationResult:
    target = ctx.output if isinstance(ctx.output, str) else str(ctx.output)
    haystack = target if ev.case_sensitive else target.lower()
    needle = ev.needle if ev.case_sensitive else ev.needle.lower()
    passed = needle in haystack
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"substring {ev.needle!r} {'found' if passed else 'not found'}",
        details={"case_sensitive": ev.case_sensitive},
    )


@register("fact_recall")
def _fact_recall(ev: FactRecallEvaluator, ctx: RunContext) -> EvaluationResult:
    target = ctx.output if isinstance(ctx.output, str) else str(ctx.output)

    fabricated = []
    hay_forbidden = target if ev.forbidden_case_sensitive else target.lower()
    for bad in ev.forbidden:
        needle = bad if ev.forbidden_case_sensitive else bad.lower()
        if needle in hay_forbidden:
            fabricated.append(bad)
    if fabricated:
        return EvaluationResult.from_check(
            ev, False, score=0.0,
            evidence=f"forbidden content present: {fabricated!r}",
            details={"fabricated": fabricated},
        )

    if not ev.facts:
        return EvaluationResult.from_check(
            ev, True, score=1.0,
            evidence="no expected facts; no forbidden content found",
        )

    recalled, missing = [], []
    for fact in ev.facts:
        hay = target if fact.case_sensitive else target.lower()
        hit = next(
            (a for a in fact.any_of
             if (a if fact.case_sensitive else a.lower()) in hay),
            None,
        )
        (recalled.append(hit) if hit is not None else missing.append(fact.any_of[0]))
    score = len(recalled) / len(ev.facts)
    passed = score >= ev.pass_threshold
    return EvaluationResult.from_check(
        ev, passed, score=score,
        evidence=(
            f"fact recall {len(recalled)}/{len(ev.facts)}"
            + (f"; missing: {missing!r}" if missing else "")
        ),
        details={"recalled": recalled, "missing": missing},
    )


@register("regex")
def _regex(ev: RegexEvaluator, ctx: RunContext) -> EvaluationResult:
    target = ctx.output if isinstance(ctx.output, str) else str(ctx.output)
    match = re.search(ev.pattern, target, ev.flags)
    passed = match is not None
    return EvaluationResult.from_check(
        ev, passed,
        evidence=(
            f"regex {ev.pattern!r} {'matched' if passed else 'did not match'}"
            + (f" at {match.span()}" if match else "")
        ),
        details={"match_span": match.span() if match else None},
    )


@register("json_path")
def _json_path(ev: JsonPathEvaluator, ctx: RunContext) -> EvaluationResult:
    found, actual = _resolve_dotted(ctx.output, ev.path)
    if not found:
        return EvaluationResult.from_check(
            ev, False,
            evidence=f"json_path {ev.path!r} not resolvable in output",
            details={"actual": None, "expected": ev.expected},
        )
    passed = actual == ev.expected
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"json_path {ev.path}: actual={actual!r} expected={ev.expected!r}",
        details={"actual": actual, "expected": ev.expected},
    )


# ------------- tool-call evaluators --------------------------------------


def _arg_subset_match(actual: dict, expected: dict) -> bool:
    return all(k in actual and actual[k] == v for k, v in expected.items())


@register("tool_called")
def _tool_called(ev: ToolCalledEvaluator, ctx: RunContext) -> EvaluationResult:
    matches = [c for c in ctx.tool_calls if c.name == ev.tool_name]
    if ev.with_args_subset is not None:
        matches = [c for c in matches if _arg_subset_match(c.args, ev.with_args_subset)]
    passed = len(matches) >= ev.min_count
    return EvaluationResult.from_check(
        ev, passed,
        evidence=(
            f"tool {ev.tool_name!r} called {len(matches)}× "
            f"(needed ≥{ev.min_count})"
        ),
        details={"match_count": len(matches), "min_count": ev.min_count},
    )


@register("tool_not_called")
def _tool_not_called(ev: ToolNotCalledEvaluator, ctx: RunContext) -> EvaluationResult:
    matches = [c for c in ctx.tool_calls if c.name == ev.tool_name]
    passed = len(matches) == 0
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"tool {ev.tool_name!r} called {len(matches)}× (expected 0)",
        details={"match_count": len(matches)},
    )


def _ordered_subsequence_end(seq: list[str], steps: tuple[str, ...]) -> int:
    """Greedily match `steps` as an ordered subsequence of `seq`.

    Returns the index in `seq` just past the last matched step, or -1 if the
    full sequence could not be matched. Used both for the pass/fail decision
    and to compute a partial-credit score.
    """
    si = 0
    for i, name in enumerate(seq):
        if si < len(steps) and name == steps[si]:
            si += 1
            if si == len(steps):
                return i + 1
    return -1


def _contiguous_run_end(seq: list[str], steps: tuple[str, ...]) -> int:
    """Find `steps` as a contiguous run in `seq`; return end index or -1."""
    if not steps:
        return 0
    n = len(steps)
    for start in range(0, len(seq) - n + 1):
        if seq[start:start + n] == list(steps):
            return start + n
    return -1


@register("path_order")
def _path_order(ev: PathOrderEvaluator, ctx: RunContext) -> EvaluationResult:
    seq = [c.name for c in ctx.tool_calls]
    if not ev.steps:
        return EvaluationResult.from_check(
            ev, True, evidence="path_order: no steps required (vacuously true)",
        )
    if ev.contiguous:
        end = _contiguous_run_end(seq, ev.steps)
        passed = end >= 0
        return EvaluationResult.from_check(
            ev, passed,
            evidence=(
                f"path_order(contiguous) {list(ev.steps)} "
                f"{'matched' if passed else 'not found'} in chain {seq}"
            ),
            # contiguous match is all-or-nothing
            score=1.0 if passed else 0.0,
            details={"chain": seq, "steps": list(ev.steps), "contiguous": True},
        )
    end = _ordered_subsequence_end(seq, ev.steps)
    passed = end >= 0
    # Partial credit: how many leading steps matched in order (helps the
    # improvement loop climb toward a fully-correct chain).
    matched = 0
    si = 0
    for name in seq:
        if si < len(ev.steps) and name == ev.steps[si]:
            si += 1
            matched += 1
    score = matched / len(ev.steps)
    return EvaluationResult.from_check(
        ev, passed,
        evidence=(
            f"path_order {list(ev.steps)} "
            f"{'matched in order' if passed else f'only {matched}/{len(ev.steps)} in order'}"
            f" in chain {seq}"
        ),
        score=score,
        details={"chain": seq, "steps": list(ev.steps), "matched": matched},
    )


# ------------- permission-introspection evaluators -----------------------


def _check_permission_present(perms: dict, key: str) -> tuple[bool, Any]:
    """Return (present, value). Present means the key is set to allow/True."""
    if key not in perms:
        return False, None
    value = perms[key]
    if isinstance(value, bool):
        return value, value
    if isinstance(value, str):
        return value == "allow", value
    if isinstance(value, dict):
        return True, value
    return False, value


@register("permission_present")
def _permission_present(
    ev: PermissionPresentEvaluator, ctx: RunContext,
) -> EvaluationResult:
    if ctx.permissions is None:
        return EvaluationResult.skip(ev, "RunContext.permissions is None")
    if ev.bash_pattern is not None:
        bash = ctx.permissions.get("bash")
        if not isinstance(bash, dict):
            return EvaluationResult.from_check(
                ev, False, evidence="bash permissions not in dict form",
            )
        value = bash.get(ev.bash_pattern)
        passed = value == "allow"
        return EvaluationResult.from_check(
            ev, passed,
            evidence=f"bash[{ev.bash_pattern!r}] = {value!r} (need 'allow')",
            details={"value": value},
        )
    passed, value = _check_permission_present(ctx.permissions, ev.permission_key)
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"permission[{ev.permission_key!r}] = {value!r}",
        details={"value": value},
    )


@register("permission_absent")
def _permission_absent(
    ev: PermissionAbsentEvaluator, ctx: RunContext,
) -> EvaluationResult:
    if ctx.permissions is None:
        return EvaluationResult.skip(ev, "RunContext.permissions is None")
    if ev.bash_pattern is not None:
        bash = ctx.permissions.get("bash")
        if not isinstance(bash, dict):
            return EvaluationResult.from_check(
                ev, True,
                evidence="bash permissions not in dict form (treated as absent)",
            )
        value = bash.get(ev.bash_pattern)
        passed = value != "allow"
        return EvaluationResult.from_check(
            ev, passed,
            evidence=f"bash[{ev.bash_pattern!r}] = {value!r} (need not-allow)",
            details={"value": value},
        )
    present, value = _check_permission_present(ctx.permissions, ev.permission_key)
    passed = not present
    return EvaluationResult.from_check(
        ev, passed,
        evidence=f"permission[{ev.permission_key!r}] = {value!r}; absent={not present}",
        details={"value": value, "present": present},
    )
