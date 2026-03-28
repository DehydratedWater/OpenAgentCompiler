"""Fluent builder for AgentConfig."""

from __future__ import annotations

from open_agent_compiler._types import (
    AgentConfig,
    CompactionConfig,
    MCPServerConfig,
    ProviderConfig,
)
from open_agent_compiler.builders._base import Builder


class ConfigBuilder(Builder[AgentConfig]):
    """Build an AgentConfig with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> ConfigBuilder:
        self._providers: list[ProviderConfig] = []
        self._default_model: str = ""
        self._compaction: CompactionConfig = CompactionConfig()
        self._mcp_servers: list[MCPServerConfig] = []
        return self

    def provider(self, provider: ProviderConfig) -> ConfigBuilder:
        self._providers.append(provider)
        return self

    def default_model(self, model: str) -> ConfigBuilder:
        self._default_model = model
        return self

    def compaction(self, *, auto: bool = True, prune: bool = True) -> ConfigBuilder:
        self._compaction = CompactionConfig(auto=auto, prune=prune)
        return self

    def mcp_server(
        self,
        name: str,
        command: str = "",
        args: list[str] | tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        *,
        url: str = "",
        headers: dict[str, str] | None = None,
    ) -> ConfigBuilder:
        """Add an MCP server.

        Local (stdio):  ``mcp_server(name="x", command="npx", args=[...])``
        Remote (HTTP):  ``mcp_server(name="x", url="https://...", headers={...})``
        """
        self._mcp_servers.append(
            MCPServerConfig(
                name=name,
                command=command,
                args=tuple(args),
                env=tuple((env or {}).items()),
                url=url,
                headers=tuple((headers or {}).items()),
            )
        )
        return self

    def build(self) -> AgentConfig:
        return AgentConfig(
            providers=tuple(self._providers),
            default_model=self._default_model,
            compaction=self._compaction,
            mcp_servers=tuple(self._mcp_servers),
        )
