"""Fluent builder for AgentConfig."""

from __future__ import annotations

from open_agent_compiler._types import AgentConfig, ModelProvider
from open_agent_compiler.builders._base import Builder


class ConfigBuilder(Builder[AgentConfig]):
    """Build an AgentConfig with a fluent API."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> ConfigBuilder:
        self._model: str = "claude-sonnet-4-5-20250929"
        self._provider: ModelProvider = ModelProvider.ANTHROPIC
        self._temperature: float = 0.0
        self._max_tokens: int = 4096
        return self

    def model(self, model: str) -> ConfigBuilder:
        self._model = model
        return self

    def provider(self, provider: ModelProvider) -> ConfigBuilder:
        self._provider = provider
        return self

    def temperature(self, temperature: float) -> ConfigBuilder:
        self._temperature = temperature
        return self

    def max_tokens(self, max_tokens: int) -> ConfigBuilder:
        self._max_tokens = max_tokens
        return self

    def build(self) -> AgentConfig:
        return AgentConfig(
            model=self._model,
            provider=self._provider,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
