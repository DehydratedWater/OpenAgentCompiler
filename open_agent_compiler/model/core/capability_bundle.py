"""ClientCapabilityBundle — merge the SaaS's built-in capability surface
with a client's own connected tools + data sources (Phase B).

The platform ships a base SaaS with built-in tools. Each client connects
their **own** tools (as MCP servers) and **data sources** (e.g. a private
Google Drive). Before a per-client compile we must collapse all three —
built-in tools ∪ client MCP tools ∪ client datasources — into ONE unified
capability surface for that client, expressed in the two forms the compiler
and runtime consume:

  1. the opencode.json `mcp` section (every client MCP server wired in), and
  2. the per-agent **tool allow-list** (built-in tool names + the tool names
     the client's MCP servers contribute).

Name collisions between a built-in tool and a client tool are resolved by an
explicit, documented policy (see CollisionPolicy below) — never silently.

Datasources are represented here as a typed seam: this phase records each
datasource and (optionally) the MCP server that backs it, but does NOT yet
turn a datasource into query/RAG tools — that is Phase C (DatasourceAdapter +
profile_datasource). `datasource_tool_names()` is the extension point a Phase
C adapter calls to register the tools it derives, so they flow into the same
merged allow-list and collision policy as everything else.

This module is pure data + pure functions (no IO, no provider calls) so it is
trivially testable and reused by the per-client compile factory.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# How an opencode MCP server is launched. opencode.json distinguishes
# `local` (stdio: a command it spawns) from `remote` (an HTTP/SSE URL).
MCPTransport = Literal["local", "remote"]

# Name-collision / precedence policy when a client tool and a built-in tool
# share a name.
#   - "namespace_client": keep both; the client tool is exposed under a
#       namespaced alias `<prefix><name>` (default prefix "client_") so the
#       built-in keeps its bare name. Safe default — nothing is shadowed.
#   - "client_overrides": the client tool wins the bare name; the built-in of
#       that name is dropped from the allow-list. Use when a client deliberately
#       replaces a built-in (e.g. their own search over the stock one).
#   - "builtin_wins": the built-in keeps the name; the colliding client tool is
#       dropped. Most conservative — the platform's surface is authoritative.
#   - "error": a collision is a hard error (fail the compile). Use in strict
#       multi-tenant setups where silent precedence is unacceptable.
CollisionPolicy = Literal[
    "namespace_client",
    "client_overrides",
    "builtin_wins",
    "error",
]


class ClientMCPServer(BaseModel):
    """A client-connected MCP server, in the shape opencode.json `mcp` wants.

    Mirrors opencode's config: a `local` server is spawned via `command`
    (argv list) with optional `environment`; a `remote` server is reached at
    `url`. `tools` lists the tool names this server exposes that the client
    wants enabled — these feed the merged per-agent allow-list. When `tools`
    is empty the server is wired into opencode.json but contributes no names
    to the allow-list assembly (the per-agent MCP allowlist still governs
    runtime access, as today).
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Server id — keys the opencode.json mcp map.")
    transport: MCPTransport = "local"
    command: tuple[str, ...] = Field(
        default=(),
        description="argv for a `local` (stdio) server, e.g. ('npx','-y','x').",
    )
    url: str | None = Field(
        default=None,
        description="Endpoint for a `remote` server (HTTP/SSE).",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Env passed to a local server. Use opencode `{env:VAR}` refs for"
            " secrets — never literal keys (cross-cutting secrets rule)."
        ),
    )
    enabled: bool = True
    tools: tuple[str, ...] = Field(
        default=(),
        description="Tool names this server exposes that the client enabled.",
    )

    @model_validator(mode="after")
    def _transport_shape(self) -> "ClientMCPServer":
        if not self.name.strip():
            raise ValueError("ClientMCPServer.name must be non-empty")
        if self.transport == "remote" and not self.url:
            raise ValueError(
                f"ClientMCPServer {self.name!r} is remote but has no url"
            )
        if self.transport == "local" and not self.command:
            raise ValueError(
                f"ClientMCPServer {self.name!r} is local but has no command"
            )
        return self

    def to_opencode_config(self) -> dict[str, Any]:
        """Serialize to one entry of the opencode.json `mcp` map's value."""
        if self.transport == "remote":
            block: dict[str, Any] = {
                "type": "remote",
                "url": self.url,
                "enabled": self.enabled,
            }
        else:
            block = {
                "type": "local",
                "command": list(self.command),
                "enabled": self.enabled,
            }
            if self.environment:
                block["environment"] = dict(self.environment)
        return block


class ClientDatasource(BaseModel):
    """A client data source (Drive, DB, vector store, …) — Phase C seam.

    This phase records the datasource and, when it arrives as an MCP server,
    the `mcp_server_name` that backs it (MCP-first, per the plan). A non-MCP
    source carries a `binding_name` pointing at an AccessProfile
    ResourceBinding instead. `derived_tools` is the extension point: a Phase C
    DatasourceAdapter, after profiling the source, sets the query/RAG tool
    names it registers — and they then flow through the SAME merge + collision
    policy as built-in and client tools. Empty here = no datasource tools yet.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Logical datasource id, e.g. 'client_drive'.")
    kind: str = Field(
        default="other",
        description="Free-form kind: 'gdrive' / 'postgres' / 'vector' / …",
    )
    mcp_server_name: str | None = Field(
        default=None,
        description="If MCP-backed, the ClientMCPServer.name serving it.",
    )
    binding_name: str | None = Field(
        default=None,
        description=(
            "If non-MCP, the AccessProfile ResourceBinding name a runtime"
            " tool resolves it through (Phase C ScriptTool.execute resources)."
        ),
    )
    derived_tools: tuple[str, ...] = Field(
        default=(),
        description=(
            "Phase C extension point: query/RAG tool names a DatasourceAdapter"
            " derives from this source. Flow into the merged allow-list."
        ),
    )

    @model_validator(mode="after")
    def _name_non_empty(self) -> "ClientDatasource":
        if not self.name.strip():
            raise ValueError("ClientDatasource.name must be non-empty")
        return self


class MergedCapabilitySurface(BaseModel):
    """The single per-client capability surface produced by merge_capabilities.

    `allow_list` is the ordered, de-duplicated per-agent tool allow-list
    (built-in tool names + enabled client MCP tool names + datasource-derived
    tool names) after the collision policy has been applied. `mcp_config` is
    the assembled opencode.json `mcp` section. `aliases` records any client
    tools that were namespaced (original name → alias) so callers can wire the
    alias through to the underlying server. `dropped` records names removed by
    a precedence policy (with a short reason) for transparency/debugging.
    """

    model_config = ConfigDict(frozen=True)

    allow_list: tuple[str, ...] = ()
    mcp_config: dict[str, Any] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    dropped: dict[str, str] = Field(default_factory=dict)

    def opencode_json_fragment(self) -> dict[str, Any]:
        """Return the `{"mcp": {...}}` fragment to merge into opencode.json."""
        return {"mcp": dict(self.mcp_config)}


class ClientCapabilityBundle(BaseModel):
    """A client's full capability inputs, ready to merge with the built-ins.

    `builtin_tools` is the SaaS's base tool name set (the platform surface).
    `mcp_servers` are the client's connected MCP servers. `datasources` are
    the client's data sources (Phase C turns these into tools). The bundle is
    pure inputs; `merge_capabilities` collapses it into one surface.
    """

    model_config = ConfigDict(frozen=True)

    client_id: str | None = Field(
        default=None,
        description="Tenant this bundle belongs to (matches CompilationContext).",
    )
    builtin_tools: tuple[str, ...] = Field(
        default=(),
        description="Base SaaS tool names every client inherits.",
    )
    mcp_servers: tuple[ClientMCPServer, ...] = ()
    datasources: tuple[ClientDatasource, ...] = ()

    def datasource_tool_names(self) -> tuple[str, ...]:
        """All tool names contributed by datasources (Phase C extension point).

        De-duplicated, order-preserving. A Phase C DatasourceAdapter populates
        each ClientDatasource.derived_tools; this collects them so they merge
        on equal footing with built-in and client MCP tools.
        """
        seen: dict[str, None] = {}
        for ds in self.datasources:
            for t in ds.derived_tools:
                seen.setdefault(t, None)
        return tuple(seen)

    def client_tool_names(self) -> tuple[str, ...]:
        """All client-contributed tool names: MCP tools ∪ datasource tools."""
        seen: dict[str, None] = {}
        for server in self.mcp_servers:
            if not server.enabled:
                continue
            for t in server.tools:
                seen.setdefault(t, None)
        for t in self.datasource_tool_names():
            seen.setdefault(t, None)
        return tuple(seen)


def _ordered_unique(*groups: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for name in group:
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def merge_capabilities(
    bundle: ClientCapabilityBundle,
    *,
    policy: CollisionPolicy = "namespace_client",
    namespace_prefix: str = "client_",
) -> MergedCapabilitySurface:
    """Collapse built-in + client MCP + datasource capabilities into one surface.

    Assembles:
      - `mcp_config`: the opencode.json `mcp` section (one entry per client
        MCP server, in declaration order), and
      - `allow_list`: the unified per-agent tool allow-list (built-in tool
        names + enabled client tool names + datasource-derived tool names),

    applying `policy` to any built-in/client name collision:

      - "namespace_client" (default): both kept; the colliding client tool is
        exposed under `<namespace_prefix><name>` so nothing is shadowed.
      - "client_overrides": the client tool keeps the bare name; the built-in
        of that name is dropped.
      - "builtin_wins": the built-in keeps the name; the client tool is dropped.
      - "error": raise ValueError on the first collision.

    An **empty-client bundle** (no MCP servers, no datasources) returns exactly
    the built-in allow-list and an empty mcp section — i.e. today's behavior.
    """
    builtin = set(bundle.builtin_tools)
    client_tools = bundle.client_tool_names()

    allow: list[str] = list(bundle.builtin_tools)
    aliases: dict[str, str] = {}
    dropped: dict[str, str] = {}

    for name in client_tools:
        if name not in builtin:
            allow.append(name)
            continue
        # Collision with a built-in tool.
        if policy == "error":
            raise ValueError(
                f"tool name collision on {name!r}: built-in and client both"
                f" define it (policy='error')"
            )
        if policy == "builtin_wins":
            dropped[name] = "client tool dropped: builtin_wins"
            continue
        if policy == "client_overrides":
            # Built-in keeps its slot in `allow` (already present); the client
            # tool simply uses that same bare name at runtime. Record the
            # override so the caller wires the name to the client's server.
            dropped[name] = "builtin shadowed: client_overrides"
            continue
        # namespace_client (default)
        alias = f"{namespace_prefix}{name}"
        aliases[name] = alias
        allow.append(alias)

    # De-duplicate while preserving order (a client may list the same tool on
    # two servers, or a datasource may echo an MCP tool name).
    allow_list = tuple(_ordered_unique(tuple(allow)))

    mcp_config: dict[str, Any] = {
        server.name: server.to_opencode_config()
        for server in bundle.mcp_servers
    }

    return MergedCapabilitySurface(
        allow_list=allow_list,
        mcp_config=mcp_config,
        aliases=aliases,
        dropped=dropped,
    )
