"""Derive JSON-Schema for tools whose handler is a ScriptTool subclass.

The compiler emits a structured tool block when an agent picks the
'json' (or 'both') format. We get the schema by importing the script
file the tool references and looking for the ScriptTool subclass —
then calling Pydantic's `.model_json_schema()` on the Input model.

Loading is best-effort: if the script can't be imported (missing dep,
import error inside the script) we fall back to a minimal schema
based on the tool's positive examples so emission never crashes the
compile. The fallback is loud (it logs via loguru) so users can fix
the underlying script.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from open_agent_compiler.model.core.tools_model import ToolDefinition
from open_agent_compiler.runtime import ScriptTool


def _load_module_from_path(path: Path) -> Any | None:
    """Import the Python file at `path` without polluting sys.modules permanently."""
    if not path.exists():
        return None
    mod_name = f"_oac_dynload_{path.stem}_{id(path)}"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - intentionally broad
        logger.warning(f"Failed to import {path}: {exc}")
        sys.modules.pop(mod_name, None)
        return None
    return module


def _find_script_tool_class(module: Any, tool_name: str) -> type[ScriptTool] | None:
    """Return the first ScriptTool subclass whose .name matches `tool_name`.

    Falls back to the first ScriptTool subclass found if no name match.
    """
    candidates: list[type[ScriptTool]] = []
    for attr in vars(module).values():
        if not isinstance(attr, type):
            continue
        if not issubclass(attr, ScriptTool) or attr is ScriptTool:
            continue
        candidates.append(attr)
    for cls in candidates:
        if getattr(cls, "name", None) == tool_name:
            return cls
    return candidates[0] if candidates else None


def derive_json_schema(tool: ToolDefinition) -> dict[str, Any] | None:
    """Return a JSON-Schema dict for the tool's Input model, or None.

    None is returned when the tool has no JSON-format contract at all,
    or when the underlying script can't be located/imported. The compiler
    treats None as "skip the json schema block for this tool."
    """
    if tool.json_tool is None or not tool.json_tool.tool_scripts:
        return None

    for tool_script in tool.json_tool.tool_scripts:
        if not tool_script.scripts:
            continue
        for script_def in tool_script.scripts:
            source = script_def.source_file_path
            if source is None or not source.exists():
                continue
            module = _load_module_from_path(source)
            if module is None:
                continue
            cls = _find_script_tool_class(module, tool.header.name)
            if cls is None:
                continue
            try:
                input_model = cls._get_input_type()
            except TypeError:
                continue
            return input_model.model_json_schema()

    return None


def tool_json_block(tool: ToolDefinition) -> dict[str, Any] | None:
    """Build the OpenCode-style tool definition block for one tool.

    Shape:
        {
            "name": "...",
            "description": "...",
            "inputSchema": { ...JSON Schema... },
        }

    Returns None if we have no schema to emit.
    """
    schema = derive_json_schema(tool)
    if schema is None:
        # Even without a schema we can still emit a stub if there's a json_tool
        # contract, so the agent at least knows the tool exists as a custom_tool.
        if tool.json_tool is None:
            return None
        return {
            "name": tool.header.name,
            "description": tool.header.description,
        }
    return {
        "name": tool.header.name,
        "description": tool.header.description,
        "inputSchema": schema,
    }
