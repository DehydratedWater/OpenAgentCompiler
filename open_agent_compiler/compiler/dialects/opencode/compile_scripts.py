"""Script copy step for the OpenCode dialect.

Two passes:
1. Per-tool scripts declared on each ToolDefinition.json_tool.tool_scripts
   — same behavior as v1.
2. Bundled infrastructure scripts (subagent_todo / workspace_io /
   opencode_manager) — conditionally copied based on which features the
   resolved tree uses, so a tree that doesn't need them stays clean.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from open_agent_compiler.model.core.agent_model import AgentVariant
from open_agent_compiler.model.core.tools_model import ToolDefinition

# Source directory for bundled scripts shipped with the package.
BUNDLED_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"


def _needs_subagent_todo(variants: dict[str, AgentVariant]) -> bool:
    return any(
        v.agent_definition.workflow and v.agent_definition.todo_mode != "none"
        for v in variants.values()
    )


def _needs_workspace_io(variants: dict[str, AgentVariant]) -> bool:
    return any(v.agent_definition.workspace for v in variants.values())


def _needs_opencode_manager(variants: dict[str, AgentVariant]) -> bool:
    """True when any agent references a primary-mode subagent.

    Primary-mode subagents are invoked via `opencode_manager.py run --agent`
    rather than the Task tool, so the bundled script must be present.
    """
    for v in variants.values():
        for sa in v.agent_definition.subagents:
            if (sa.mode or "subagent") == "primary":
                return True
    return False


def bundled_scripts_required(variants: dict[str, AgentVariant]) -> list[str]:
    """Return the bundled script filenames the tree needs."""
    out: list[str] = []
    if _needs_subagent_todo(variants):
        out.append("subagent_todo.py")
    if _needs_workspace_io(variants):
        out.append("workspace_io.py")
    if _needs_opencode_manager(variants):
        out.append("opencode_manager.py")
    return out


def copy_bundled_scripts(target: Path, names: list[str]) -> list[Path]:
    """Copy the named bundled scripts from open_agent_compiler/scripts/ to target/scripts/.

    Returns the list of written paths so callers can report what was added.
    """
    scripts_dir = target / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in names:
        source = BUNDLED_SCRIPTS_DIR / name
        if not source.exists():
            raise FileNotFoundError(
                f"Bundled script {name!r} not found at {source}."
                " Did the open_agent_compiler/scripts/ package layout change?"
            )
        dest = scripts_dir / name
        shutil.copy(source, dest)
        written.append(dest)
    return written


def compile_scripts(
    target: Path,
    tools: list[ToolDefinition],
    variants: dict[str, AgentVariant] | None = None,
) -> None:
    """Write per-tool scripts and any bundled infrastructure the tree needs.

    `variants` is optional for backward compat — when omitted, only
    per-tool scripts are copied. The OpenCodeCompiler passes the resolved
    tree so the bundled-script auto-include can run.
    """
    scripts_dir = target / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    for tool in tools:
        if not tool.json_tool or not tool.json_tool.tool_scripts:
            continue
        for tool_script in tool.json_tool.tool_scripts:
            if not tool_script.scripts:
                continue
            for script in tool_script.scripts:
                dest_path = target / script.target_file_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                if script.script_contents is not None:
                    dest_path.write_text(script.script_contents)
                elif script.source_file_path is not None:
                    if script.source_file_path.exists():
                        shutil.copy(script.source_file_path, dest_path)
                    else:
                        raise FileNotFoundError(
                            f"Source file {script.source_file_path} not found"
                        )

    if variants is not None:
        copy_bundled_scripts(target, bundled_scripts_required(variants))
