"""Apply a promoted winner back into the Python SOURCE definition.

`apply_promoted_to_agent` merges an improvement at *compile time* — the
Python baseline stays weak and the promotion file must travel with the
project. Sometimes the user wants the opposite: make the improvement the
new checked-in baseline by *rewriting the prompt inside the Python
file*, then delete the promotion. This module does that surgically:

1. Parse the file with `ast` and locate the `AgentDefinition(...)` call
   whose `header=AgentHeader(agent_id="<component_id>")` (falling back
   to `name="<component_id>"`).
2. Find its `system_prompt=` keyword, which must be a plain string
   literal (f-strings / concatenations / variables are refused — we
   won't guess at dynamic code).
3. Splice the new prompt over the literal's exact source span, leaving
   every other byte of the file untouched.

Refusals raise `SourceApplyError` with a message pointing at the
compile-time merge as the fallback. The CLI face is
`oac versions apply-source` (cli/commands/versions.py).
"""

from __future__ import annotations

import ast
from pathlib import Path


class SourceApplyError(RuntimeError):
    pass


def _py_literal(text: str) -> str:
    """A readable Python literal for `text`.

    Multi-line prompts render as a triple-quoted string (escaping
    backslashes and any embedded triple quotes); single-line prompts use
    repr(). Both round-trip exactly.
    """
    if "\n" not in text:
        return repr(text)
    escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if escaped.endswith('"'):
        escaped = escaped[:-1] + '\\"'
    return f'"""{escaped}"""'


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _keyword(node: ast.Call, name: str) -> ast.keyword | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw
    return None


def _matches_component(call: ast.Call, component_id: str) -> bool:
    """True when this AgentDefinition call's header names `component_id`."""
    header = _keyword(call, "header")
    if header is None or not isinstance(header.value, ast.Call):
        return False
    if _call_name(header.value) != "AgentHeader":
        return False
    for field in ("agent_id", "name"):
        kw = _keyword(header.value, field)
        if (
            kw is not None
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == component_id
        ):
            return True
    return False


def _span_to_offsets(source: str, node: ast.expr) -> tuple[int, int]:
    """Absolute (start, end) character offsets for a node's source span."""
    lines = source.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))
    start = line_starts[node.lineno - 1] + node.col_offset
    end = line_starts[node.end_lineno - 1] + node.end_col_offset
    return start, end


def apply_prompt_to_source(
    py_file: Path,
    component_id: str,
    new_prompt: str,
    *,
    write: bool = True,
) -> str:
    """Replace the `system_prompt` literal of `component_id`'s definition.

    Returns the rewritten source (written back to `py_file` unless
    `write=False` — useful for --dry-run diffs). Raises SourceApplyError
    when the definition or a rewritable literal can't be found.
    """
    source = py_file.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SourceApplyError(f"{py_file} does not parse: {exc}") from exc

    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _call_name(node) == "AgentDefinition"
        and _matches_component(node, component_id)
    ]
    if not matches:
        raise SourceApplyError(
            f"no AgentDefinition with header agent_id/name ="
            f" {component_id!r} found in {py_file}; use"
            " apply_promoted_to_agent for compile-time merging instead"
        )
    if len(matches) > 1:
        raise SourceApplyError(
            f"{len(matches)} AgentDefinition calls match {component_id!r}"
            f" in {py_file} — refusing to guess"
        )

    call = matches[0]
    prompt_kw = _keyword(call, "system_prompt")
    if prompt_kw is None:
        raise SourceApplyError(
            f"the {component_id!r} definition has no system_prompt="
            " keyword to rewrite"
        )
    value = prompt_kw.value
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        raise SourceApplyError(
            f"{component_id!r}'s system_prompt is not a plain string"
            " literal (f-string / variable / concatenation) — rewrite it"
            " manually or keep using the compile-time merge"
        )

    start, end = _span_to_offsets(source, value)
    rewritten = source[:start] + _py_literal(new_prompt) + source[end:]
    # Guarantee we produced valid Python before touching the file.
    ast.parse(rewritten)
    if write:
        py_file.write_text(rewritten)
    return rewritten
