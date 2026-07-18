"""Derived datasource tools — turn a profile into declarative tool specs.

From a `DatasourceProfile` we generate the query/RAG tools an agent needs
to navigate the client's source, as DECLARATIVE specs (name + description +
input schema) — NOT live implementations. The names then populate
`ClientDatasource.derived_tools`, so they flow through the existing
`merge_capabilities` path on equal footing with built-in and client MCP
tools (same merged allow-list, same collision policy).

Two tools are derived per datasource:

  * `search_<name>` — a search/RAG query over the source, with the
    profiled relevant-locations and naming convention baked into the
    description so the agent knows WHERE to look.
  * `read_<name>_by_path` — fetch one item by its canonical path.

`apply_profile_to_datasource(ClientDatasource, profile)` returns a NEW
frozen `ClientDatasource` with `derived_tools` populated (immutable
update), ready to drop back into a `ClientCapabilityBundle`. Phase E later
realizes each spec as a live MCP call (Drive search/read) or a ScriptTool
bound through the AccessProfile.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.datasource.profile import DatasourceProfile
from open_agent_compiler.model.core.capability_bundle import ClientDatasource

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Normalize a datasource name into a tool-name-safe slug."""
    s = _SLUG.sub("_", name.strip().lower()).strip("_")
    return s or "datasource"


class ToolInputSchema(BaseModel):
    """A minimal JSON-schema-shaped declaration of a tool's inputs.

    Declarative only: lists the parameter names, their JSON types, which
    are required, and per-param descriptions. `to_json_schema()` renders a
    standard JSON Schema object that opencode / LangChain tool wiring (Phase
    E) consumes.
    """

    model_config = ConfigDict(frozen=True)

    properties: dict[str, str] = Field(
        default_factory=dict,
        description="param name → JSON type ('string' / 'integer' / …).",
    )
    required: tuple[str, ...] = ()
    descriptions: dict[str, str] = Field(default_factory=dict)

    def to_json_schema(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for pname, ptype in self.properties.items():
            entry: dict[str, Any] = {"type": ptype}
            if pname in self.descriptions:
                entry["description"] = self.descriptions[pname]
            props[pname] = entry
        return {
            "type": "object",
            "properties": props,
            "required": list(self.required),
        }


class DerivedToolSpec(BaseModel):
    """A declarative spec for one tool derived from a datasource profile.

    `name` is the tool's id (flows into the merged allow-list).
    `description` embeds the profiled layout hints so the agent knows how to
    use it. `input_schema` declares the inputs. `datasource_name` ties the
    spec back to its source; `mcp_server_name` / `binding_name` record which
    realization path Phase E should use (MCP call vs AccessProfile-bound
    ScriptTool). No live behaviour here — realization is Phase E.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: ToolInputSchema = Field(default_factory=ToolInputSchema)
    datasource_name: str = ""
    kind: str = "search"  # "search" | "read"
    mcp_server_name: str | None = None
    binding_name: str | None = None


def derive_datasource_tools(
    profile: DatasourceProfile,
    *,
    mcp_server_name: str | None = None,
    binding_name: str | None = None,
) -> tuple[DerivedToolSpec, ...]:
    """Generate the search + read-by-path tool specs for a profiled source.

    The descriptions embed the profiled relevant-locations / naming
    convention so the agent gets navigation guidance for free. Pass the
    `mcp_server_name` (MCP path) or `binding_name` (AccessProfile path) so
    Phase E knows how to realize each spec.
    """
    slug = _slug(profile.datasource_name)
    locations = (
        "; ".join(profile.relevant_locations)
        if profile.relevant_locations
        else profile.root
    )
    naming_hint = (
        f" Files generally follow {profile.naming_convention} naming."
        if profile.naming_convention not in ("unknown", "mixed")
        else ""
    )

    search = DerivedToolSpec(
        name=f"search_{slug}",
        kind="search",
        datasource_name=profile.datasource_name,
        mcp_server_name=mcp_server_name,
        binding_name=binding_name,
        description=(
            f"Search the client's {profile.kind} datasource"
            f" '{profile.datasource_name}'. Relevant data mostly lives under:"
            f" {locations}.{naming_hint} Returns matching items with their"
            f" canonical paths; follow up with read_{slug}_by_path to fetch"
            f" contents."
        ),
        input_schema=ToolInputSchema(
            properties={"query": "string", "max_results": "integer"},
            required=("query",),
            descriptions={
                "query": "Natural-language or keyword search over the source.",
                "max_results": "Maximum items to return (default applied by runtime).",
            },
        ),
    )

    read = DerivedToolSpec(
        name=f"read_{slug}_by_path",
        kind="read",
        datasource_name=profile.datasource_name,
        mcp_server_name=mcp_server_name,
        binding_name=binding_name,
        description=(
            f"Read one item from the client's '{profile.datasource_name}'"
            f" datasource by its canonical path (as returned by"
            f" search_{slug}). Root is {profile.root!r}."
        ),
        input_schema=ToolInputSchema(
            properties={"path": "string"},
            required=("path",),
            descriptions={
                "path": "Canonical item path, e.g. from a search result.",
            },
        ),
    )

    return (search, read)


def apply_profile_to_datasource(
    datasource: ClientDatasource,
    profile: DatasourceProfile,
) -> ClientDatasource:
    """Return a new ClientDatasource with derived_tools populated.

    Generates the tool specs from `profile`, takes their names, and writes
    them onto a frozen copy of `datasource` (immutable update). The result
    drops straight into a `ClientCapabilityBundle`; its `derived_tools` then
    flow through `merge_capabilities` (via `datasource_tool_names()`).

    The MCP vs AccessProfile realization path is inferred from the
    datasource's own `mcp_server_name` / `binding_name`.
    """
    specs = derive_datasource_tools(
        profile,
        mcp_server_name=datasource.mcp_server_name,
        binding_name=datasource.binding_name,
    )
    names = tuple(spec.name for spec in specs)
    return datasource.model_copy(update={"derived_tools": names})
