"""Fluent builder for AgentConfig."""

from __future__ import annotations

from open_agent_compiler._types import AgentConfig, CompactionConfig, ProviderConfig
from open_agent_compiler.builders._base import Builder


class ConfigBuilder(Builder[AgentConfig]):
    """Build an AgentConfig with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> ConfigBuilder:
        self._providers: list[ProviderConfig] = []
        self._default_model: str = ""
        self._compaction: CompactionConfig = CompactionConfig()
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

    def build(self) -> AgentConfig:
        return AgentConfig(
            providers=tuple(self._providers),
            default_model=self._default_model,
            compaction=self._compaction,
        )
