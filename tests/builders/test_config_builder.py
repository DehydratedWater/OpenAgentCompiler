"""Tests for ConfigBuilder."""

import pytest

from open_agent_compiler._types import CompactionConfig, ProviderConfig, ProviderOptions
from open_agent_compiler.builders import ConfigBuilder


class TestConfigBuilder:
    def test_build_defaults(self, config_builder: ConfigBuilder):
        config = config_builder.build()
        assert config.providers == ()
        assert config.default_model == ""
        assert config.compaction == CompactionConfig()

    def test_build_with_provider(self, config_builder: ConfigBuilder):
        prov = ProviderConfig(
            name="anthropic",
            options=ProviderOptions(api_key="sk-test"),
        )
        config = config_builder.provider(prov).default_model("anthropic/sonnet").build()
        assert len(config.providers) == 1
        assert config.providers[0].name == "anthropic"
        assert config.default_model == "anthropic/sonnet"

    def test_build_with_compaction(self, config_builder: ConfigBuilder):
        config = config_builder.compaction(auto=False, prune=True).build()
        assert config.compaction.auto is False
        assert config.compaction.prune is True

    def test_multiple_providers(self, config_builder: ConfigBuilder):
        p1 = ProviderConfig(name="anthropic")
        p2 = ProviderConfig(name="openai")
        config = config_builder.provider(p1).provider(p2).build()
        assert len(config.providers) == 2
        assert config.providers[0].name == "anthropic"
        assert config.providers[1].name == "openai"

    def test_fluent_returns_self(self, config_builder: ConfigBuilder):
        ret = config_builder.default_model("x")
        assert ret is config_builder

    def test_reset_restores_defaults(self, config_builder: ConfigBuilder):
        prov = ProviderConfig(name="test")
        config_builder.provider(prov).default_model("test/m")
        config_builder.reset()
        config = config_builder.build()
        assert config.providers == ()
        assert config.default_model == ""

    def test_built_config_is_frozen(self, config_builder: ConfigBuilder):
        config = config_builder.build()
        with pytest.raises(AttributeError):
            config.default_model = "y"  # type: ignore[misc]
