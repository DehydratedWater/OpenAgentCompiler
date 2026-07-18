"""Compile an AgentDefinition as a one-off primary agent for evaluation.

Subagent-mode agents can't be invoked directly via `opencode run --agent
<name>` — opencode falls back to the default primary and only reaches
the subagent through Task. That's correct for production but breaks
autoresearch: when you want to score N candidate prompts for the same
subagent, each candidate needs its own opencode invocation.

`write_test_variant_md()` writes a temp file under
`<project>/build/.opencode/agents/<base>-test-<random>.md` with the same
system_prompt + permissions as the agent definition, but with
`mode: primary`. The eval driver invokes opencode against that name,
captures output, and deletes the file afterward.

For higher fidelity, the evaluator can ALSO use a "parent-mimic"
prompt — an LLM-constructed user message in the same shape the
real orchestrator would have sent — via `build_parent_mimic_prompt()`.
That keeps the test conditions close to production rather than
inventing arbitrary inputs.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Protocol


class _LikeAgent(Protocol):
    """Structural shape an evaluation accepts.

    Either a real `AgentDefinition` or anything carrying the same
    fields used below (system_prompt, header, model_class, …).
    """

    system_prompt: str


def write_test_variant_md(
    agent_definition: Any,
    *,
    build_dir: Path,
    model: str,
    temperature: float = 0.0,
    name_prefix: str | None = None,
    extra_permissions: dict[str, Any] | None = None,
) -> tuple[str, Path]:
    """Emit a primary-mode .md the eval driver can invoke directly.

    Returns (agent_name_for_opencode, path_written). Caller is expected
    to delete the path after the eval pass — keep these short-lived so
    they don't pollute the agents/ directory between runs.

    The MD carries:
      - mode: primary           (so `opencode run --agent <name>` works)
      - the agent's system_prompt verbatim
      - a deny-by-default permission block plus optional extras

    Use `extra_permissions={"task": "allow"}` if the agent normally has
    Task; `{"bash": {"uv run ...": "allow"}}` if it needs a bash tool.
    For pure-LLM agents (the common autoresearch target — a judge or
    scorer) the default deny-all is fine.
    """
    name_base = name_prefix or "eval_variant"
    suffix = secrets.token_hex(4)
    agent_name = f"{name_base}_{suffix}"

    # Accept either an AgentDefinition object OR a plain dict
    # (e.g. version.definition from a ComponentVersion). Dicts are
    # common in autoresearch evaluators where versions are dict-shaped
    # by construction.
    def _field(name: str, default: Any = None) -> Any:
        if isinstance(agent_definition, dict):
            return agent_definition.get(name, default)
        return getattr(agent_definition, name, default)

    header = _field("header")
    if isinstance(header, dict):
        description = header.get("description")
    else:
        description = getattr(header, "description", None) if header else None
    description = description or "test-variant of a subagent, compiled as primary for eval"
    system_prompt = _field("system_prompt", "") or ""

    permissions: dict[str, Any] = {"*": "deny"}
    if extra_permissions:
        permissions.update(extra_permissions)

    md = (
        "---\n"
        f"description: {json.dumps(description)}\n"
        f"model: {model}\n"
        "mode: primary\n"
        f"temperature: {temperature}\n"
        "permission:\n"
    )
    md += _yaml_block(permissions, indent=2)
    md += "tool:\n"
    md += _yaml_block(
        {
            "read": False, "write": False, "edit": False,
            "task": False, "bash": False, "mcp": False,
        },
        indent=2,
    )
    md += "---\n\n" + system_prompt

    agents_dir = build_dir / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    out_path = agents_dir / f"{agent_name}.md"
    out_path.write_text(md)
    return agent_name, out_path


def _yaml_block(d: dict[str, Any], *, indent: int) -> str:
    """Tiny YAML emitter for the simple permission/tool dicts.

    We don't pull in pyyaml as a runtime dep for this — the supported
    shapes are: scalar (bool/string), or one-level-nested dict whose
    leaves are scalars. That's what the permission/tool blocks need.
    """
    pad = " " * indent
    lines: list[str] = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{_yaml_key(k)}:")
            for kk, vv in v.items():
                lines.append(
                    f"{pad}  {_yaml_key(kk)}: {_yaml_scalar(vv)}"
                )
        else:
            lines.append(f"{pad}{_yaml_key(k)}: {_yaml_scalar(v)}")
    return "\n".join(lines) + "\n"


def _yaml_key(k: str) -> str:
    if any(c in k for c in " :*'\""):
        return json.dumps(k)
    return k


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v))


def build_parent_mimic_prompt(
    *,
    target_agent_name: str,
    target_description: str,
    eval_case: dict[str, Any],
    parent_description: str | None = None,
) -> str:
    """Construct a user message that mimics what the parent orchestrator
    would have sent to this subagent in production.

    For a subagent that normally gets invoked by Task with carefully
    crafted args, just sending raw eval-case data ("here's a transcript,
    score it") may not exercise the same prompt-handling code path as
    the production invocation. This helper composes the eval_case into
    a user message that looks like what the parent orchestrator would
    say.

    Pattern:
      - `target_agent_name`: who's being invoked.
      - `target_description`: one-line of what the subagent is for.
      - `parent_description`: optional, who's calling.
      - `eval_case`: the per-case data (excerpt, query, etc).

    Returns a single prompt string the eval driver passes to opencode.

    For LLM-constructed mimicry (an LLM playing the parent role to
    write a more realistic user message), wrap this in an LLM call
    yourself — the helper just provides the deterministic template
    the LLM can refine.
    """
    parent_line = (
        f"You are being invoked by the {parent_description!r} agent."
        if parent_description else
        "You are being invoked by a parent orchestrator."
    )
    case_lines: list[str] = []
    for key, val in eval_case.items():
        if key in ("id", "expected_score"):
            continue
        if isinstance(val, str) and "\n" in val:
            case_lines.append(f"\n**{key}:**\n```\n{val}\n```")
        else:
            case_lines.append(f"- **{key}**: {val}")
    body = "\n".join(case_lines)
    return (
        f"{parent_line}\n\n"
        f"Run as agent {target_agent_name!r}.\n"
        f"Purpose: {target_description}\n\n"
        f"Input:\n{body}\n"
    )
