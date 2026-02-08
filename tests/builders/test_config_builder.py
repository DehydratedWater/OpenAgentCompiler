"""Tests for ConfigBuilder."""

import pytest

from open_agent_compiler._types import ModelProvider
from open_agent_compiler.builders import ConfigBuilder


class TestConfigBuilder:
    def test_build_defaults(self, config_builder: ConfigBuilder):
        config = config_builder.build()
        assert config.model == "claude-sonnet-4-5-20250929"
        assert config.provider == ModelProvider.ANTHROPIC
        assert config.temperature == 0.0
        assert config.max_tokens == 4096

    def test_build_custom(self, config_builder: ConfigBuilder):
        config = (
            config_builder.model("gpt-4o")
            .provider(ModelProvider.OPENAI)
            .temperature(0.7)
            .max_tokens(2048)
            .build()
        )
        assert config.model == "gpt-4o"
        assert config.provider == ModelProvider.OPENAI
        assert config.temperature == 0.7
        assert config.max_tokens == 2048

    def test_fluent_returns_self(self, config_builder: ConfigBuilder):
        ret = config_builder.model("x")
        assert ret is config_builder

    def test_reset_restores_defaults(self, config_builder: ConfigBuilder):
        config_builder.model("custom").temperature(1.0)
        config_builder.reset()
        config = config_builder.build()
        assert config.model == "claude-sonnet-4-5-20250929"
        assert config.temperature == 0.0

    def test_built_config_is_frozen(self, config_builder: ConfigBuilder):
        config = config_builder.build()
        with pytest.raises(AttributeError):
            config.model = "y"  # type: ignore[misc]
