"""Rebuild a Pydantic model from a ToolSpec's JSON input schema.

`build_interactive_spec` derives each tool's `input_schema` from the
backing ScriptTool's real Pydantic Input model (the same derivation the
compiler uses for native tools). The bindings then need to hand their
framework something *typed* — LangChain wants an `args_schema` model,
PydanticAI infers from the function signature. This module turns the
JSON schema's top level back into a dynamic Pydantic model.

Only the top level is mapped (scalars, defaults, descriptions,
required-ness); nested structures degrade to `Any` because the Python
side re-validates with the real Input model at execution time — the
binding layer needs to be permissive-but-typed, never authoritative.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, create_model

_PY_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def model_from_input_schema(
    name: str, schema: dict[str, Any] | None,
) -> type[BaseModel] | None:
    """A dynamic Pydantic model for `schema`'s top level, or None.

    None means "no usable schema" — callers fall back to the classic
    single `input: str` contract.
    """
    if not schema or not isinstance(schema.get("properties"), dict):
        return None
    props: dict[str, Any] = schema["properties"]
    if not props:
        return None
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for field_name, prop in props.items():
        if not isinstance(prop, dict):
            prop = {}
        py_type: Any = _PY_TYPES.get(str(prop.get("type")), Any)
        description = prop.get("description")
        if field_name in required and "default" not in prop:
            fields[field_name] = (py_type, Field(description=description))
        else:
            fields[field_name] = (
                py_type | None,
                Field(default=prop.get("default"), description=description),
            )
    safe = "".join(c if c.isalnum() else "_" for c in name) or "Tool"
    return create_model(f"{safe.title()}Args", **fields)
