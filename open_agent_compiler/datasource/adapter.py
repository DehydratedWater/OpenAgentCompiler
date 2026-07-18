"""DatasourceAdapter — a uniform interface over a connected data source.

A `DatasourceAdapter` abstracts three operations the profiler needs:

    connect()                -> establish/verify the connection (idempotent)
    enumerate_structure()    -> the source's layout (folders / files / tables)
    sample(n)                -> up to n representative leaf items

plus metadata (`kind`, `name`). Concrete adapters differ only in HOW they
fetch — the profiler is written once against this interface.

Two concrete shapes ship:

  * `MCPDatasourceAdapter` (MCP-first, the reference path) — wraps a
    client-connected MCP server. Google Drive is the reference example:
    its folder/file hierarchy arrives via MCP tool calls. The *actual*
    MCP calls are isolated behind an injected `MCPEnumerator` protocol so
    this class stays pure/testable: tests pass a mock enumerator returning
    a canned folder tree, no live MCP / Drive / network.

  * `ResourceBindingAdapter` (non-MCP path) — wraps an `AccessProfile`
    `ResourceBinding` (DB / API). The concrete fetch is an injected
    `ResourceBindingEnumerator` so DB schema introspection / API listing
    is mockable the same way.

The injected enumerator is the ONLY IO seam. Everything else — the
`DatasourceStructure` / `DatasourceItem` models, and `profile_datasource`
that consumes them — is pure data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from open_agent_compiler.model.core.access_profile import ResourceBinding

# Kind of datasource. 'gdrive' is the reference MCP-backed example; the rest
# cover the common non-MCP sources. Free-form 'other' is the escape hatch and
# matches ClientDatasource.kind's vocabulary.
DatasourceKind = Literal[
    "gdrive",
    "fs",
    "postgres",
    "mysql",
    "sqlite",
    "vector",
    "api",
    "other",
]


class DatasourceItem(BaseModel):
    """One node in a datasource's structure.

    Deliberately generic so it can describe a Drive folder/file, a DB
    table/column, or an API resource. `path` is the canonical address
    used by the derived read-by-path tool (e.g. a Drive folder path, a
    `schema.table` for a DB). `is_container` distinguishes a folder /
    table-group from a leaf file / row-bearing table. `item_type` is a
    coarse type label (folder / file extension / 'table' / 'collection').
    `size` / `mime` / `extra` are optional enrichment used by the
    convention-inference heuristics.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Canonical address of this node.")
    name: str = Field(description="Display name (basename / table name).")
    is_container: bool = Field(
        default=False,
        description="True for a folder / schema / collection; False for a leaf.",
    )
    item_type: str = Field(
        default="",
        description="Coarse type: 'folder', a file extension, 'table', …",
    )
    size: int | None = Field(default=None, description="Bytes, if known.")
    mime: str | None = Field(default=None, description="MIME type, if known.")
    extra: dict[str, str] = Field(
        default_factory=dict,
        description="Adapter-specific metadata (owner, modified, …).",
    )

    @model_validator(mode="after")
    def _path_non_empty(self) -> "DatasourceItem":
        if not self.path.strip():
            raise ValueError("DatasourceItem.path must be non-empty")
        return self


class DatasourceStructure(BaseModel):
    """The enumerated layout of a datasource.

    `items` is the flat list of nodes (containers + leaves) discovered by
    `enumerate_structure`. `root` is the logical root address. `truncated`
    flags that enumeration stopped early (large source) so the profiler can
    note the layout is partial. The structure is intentionally flat (each
    item carries its full `path`) so it serializes cleanly and the profiler
    can reconstruct the tree without a recursive model.
    """

    model_config = ConfigDict(frozen=True)

    root: str = Field(default="/", description="Logical root address.")
    items: tuple[DatasourceItem, ...] = ()
    truncated: bool = Field(
        default=False,
        description="True if enumeration was capped before completion.",
    )

    def containers(self) -> tuple[DatasourceItem, ...]:
        return tuple(i for i in self.items if i.is_container)

    def leaves(self) -> tuple[DatasourceItem, ...]:
        return tuple(i for i in self.items if not i.is_container)


@runtime_checkable
class MCPEnumerator(Protocol):
    """The IO seam for an MCP-backed datasource (e.g. a Drive MCP server).

    A real implementation issues MCP tool calls (list folders, list files)
    against the client's connected server. Tests supply a mock returning a
    canned structure / sample — keeping `MCPDatasourceAdapter` pure and the
    whole module network-free.
    """

    def enumerate(self, *, root: str) -> DatasourceStructure: ...

    def sample(self, *, n: int) -> tuple[DatasourceItem, ...]: ...


@runtime_checkable
class ResourceBindingEnumerator(Protocol):
    """The IO seam for a non-MCP datasource bound via a ResourceBinding.

    A real implementation introspects a DB schema / lists an API's
    resources using `binding.config`. Tests supply a mock.
    """

    def enumerate(
        self, *, binding: ResourceBinding, root: str
    ) -> DatasourceStructure: ...

    def sample(
        self, *, binding: ResourceBinding, n: int
    ) -> tuple[DatasourceItem, ...]: ...


class DatasourceAdapter(ABC, BaseModel):
    """Uniform interface over a connected data source.

    Subclasses implement `connect`, `enumerate_structure`, `sample`. The
    `kind` / `name` metadata identifies the source for the profile and the
    derived tools. `binding_name` / `mcp_server_name` carry the link back
    to the `ClientDatasource` / capability bundle so `apply_profile_to_*`
    can populate the right record.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    name: str = Field(description="Logical datasource id (matches ClientDatasource.name).")
    kind: DatasourceKind = "other"

    @abstractmethod
    def connect(self) -> None:
        """Establish / verify the connection. Idempotent; no-op if ready."""
        raise NotImplementedError

    @abstractmethod
    def enumerate_structure(self) -> DatasourceStructure:
        """Return the source's layout (folders / files / tables)."""
        raise NotImplementedError

    @abstractmethod
    def sample(self, n: int = 5) -> tuple[DatasourceItem, ...]:
        """Return up to `n` representative leaf items."""
        raise NotImplementedError


class MCPDatasourceAdapter(DatasourceAdapter):
    """MCP-first adapter — wraps a client-connected MCP server.

    Google Drive is the reference example: the client connects their Drive
    as an MCP server (`mcp_server_name` keys the opencode.json mcp map), and
    its folder/file hierarchy is fetched through `enumerator`. The
    enumerator is the only IO; in tests it is a mock returning a canned
    Drive tree, so no live MCP / Drive / network is touched.
    """

    enumerator: MCPEnumerator = Field(
        description="Injected MCP IO seam (mocked in tests).",
    )
    mcp_server_name: str = Field(
        description="ClientMCPServer.name backing this datasource.",
    )
    root: str = Field(default="/", description="Logical root to enumerate from.")
    _connected: bool = False

    @model_validator(mode="after")
    def _names_non_empty(self) -> "MCPDatasourceAdapter":
        if not self.name.strip():
            raise ValueError("MCPDatasourceAdapter.name must be non-empty")
        if not self.mcp_server_name.strip():
            raise ValueError("MCPDatasourceAdapter.mcp_server_name must be non-empty")
        return self

    def connect(self) -> None:
        # No network here: connection is realized by opencode wiring the MCP
        # server. We just mark ready so enumerate/sample can be called.
        self._connected = True

    def enumerate_structure(self) -> DatasourceStructure:
        if not self._connected:
            self.connect()
        return self.enumerator.enumerate(root=self.root)

    def sample(self, n: int = 5) -> tuple[DatasourceItem, ...]:
        if not self._connected:
            self.connect()
        if n < 0:
            raise ValueError("sample(n): n must be >= 0")
        return self.enumerator.sample(n=n)


class ResourceBindingAdapter(DatasourceAdapter):
    """Non-MCP adapter — wraps an AccessProfile ResourceBinding (DB / API).

    `binding` is the resolved `ResourceBinding` (kind + opaque config); the
    injected `enumerator` introspects it (DB schema / API listing). `binding_name`
    is the symbolic name a runtime ScriptTool resolves the binding through,
    and is recorded onto the `ClientDatasource` so derived tools route via the
    AccessProfile rather than via MCP.
    """

    binding: ResourceBinding = Field(description="The resolved resource binding.")
    binding_name: str = Field(
        description="Symbolic ResourceBinding name (AccessProfile key).",
    )
    enumerator: ResourceBindingEnumerator = Field(
        description="Injected DB/API IO seam (mocked in tests).",
    )
    root: str = Field(default="", description="Logical root (e.g. schema name).")
    _connected: bool = False

    @model_validator(mode="after")
    def _names_non_empty(self) -> "ResourceBindingAdapter":
        if not self.name.strip():
            raise ValueError("ResourceBindingAdapter.name must be non-empty")
        if not self.binding_name.strip():
            raise ValueError("ResourceBindingAdapter.binding_name must be non-empty")
        return self

    def connect(self) -> None:
        self._connected = True

    def enumerate_structure(self) -> DatasourceStructure:
        if not self._connected:
            self.connect()
        return self.enumerator.enumerate(binding=self.binding, root=self.root)

    def sample(self, n: int = 5) -> tuple[DatasourceItem, ...]:
        if not self._connected:
            self.connect()
        if n < 0:
            raise ValueError("sample(n): n must be >= 0")
        return self.enumerator.sample(binding=self.binding, n=n)
