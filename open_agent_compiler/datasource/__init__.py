"""Datasource adapters + automatic structure profiling (Phase C).

The per-client SaaS platform lets a client connect their **own** data
source — most importantly a custom Google Drive whose folder layout,
naming conventions and "where the real data lives" are unknown to the
platform up front. Phase C makes that automatic:

  1. `DatasourceAdapter` — a uniform interface over a connected source.
     The primary, MCP-first concrete adapter (`MCPDatasourceAdapter`)
     wraps a **client-connected MCP server** (Google Drive being the
     reference example: folders / files / hierarchy). A second shape,
     `ResourceBindingAdapter`, covers non-MCP sources (DB / API) via an
     `AccessProfile` `ResourceBinding`.

  2. `profile_datasource(adapter) -> DatasourceProfile` — enumerate the
     source's structure, sample a few items, and INFER conventions
     (layout summary, where relevant data lives, naming patterns) into a
     Pydantic `DatasourceProfile` with structured fields + a
     human-readable `summary` string.

  3. `derive_datasource_tools(profile) -> tuple[DerivedToolSpec, ...]`
     and `apply_profile_to_datasource(...)` — turn the profile into
     declarative query/RAG tool specs (search / read-by-path) and
     populate `ClientDatasource.derived_tools` so they flow through the
     existing `merge_capabilities` path on equal footing with built-in
     and client MCP tools.

  4. `DatasourceProfile.context_block()` — expose the profile summary as
     a `ContextBlock` the personalized compile (Phase E) can inject into
     an agent's prompt so the agent KNOWS the client's structure.

Everything here is pure data + pure functions over an adapter abstraction.
The adapters' IO boundary (`connect` / `enumerate_structure` / `sample`)
is the ONLY place a live MCP / DB call would happen — and in tests it is
always a MOCK returning a canned structure. No live MCP, Drive, opencode,
qwen, or network is ever touched by this module.
"""

from __future__ import annotations

from open_agent_compiler.datasource.adapter import (
    DatasourceAdapter,
    DatasourceItem,
    DatasourceKind,
    DatasourceStructure,
    MCPDatasourceAdapter,
    MCPEnumerator,
    ResourceBindingAdapter,
    ResourceBindingEnumerator,
)
from open_agent_compiler.datasource.profile import (
    DatasourceProfile,
    NamingConvention,
    profile_datasource,
)
from open_agent_compiler.datasource.tools import (
    DerivedToolSpec,
    ToolInputSchema,
    apply_profile_to_datasource,
    derive_datasource_tools,
)

__all__ = [
    # adapter interface + concrete shapes
    "DatasourceAdapter",
    "DatasourceItem",
    "DatasourceKind",
    "DatasourceStructure",
    "MCPDatasourceAdapter",
    "MCPEnumerator",
    "ResourceBindingAdapter",
    "ResourceBindingEnumerator",
    # profiling
    "DatasourceProfile",
    "NamingConvention",
    "profile_datasource",
    # derived tools + context seam
    "DerivedToolSpec",
    "ToolInputSchema",
    "derive_datasource_tools",
    "apply_profile_to_datasource",
]
