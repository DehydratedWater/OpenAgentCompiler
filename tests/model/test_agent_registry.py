"""Agent registry behavior tests."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry


def test_agent_id_is_generated_from_name_and_model(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
) -> None:
    reg = AgentRegistry()
    agent_id = reg.register_agent("joke", minimal_agent, fast_model)
    assert agent_id == "joke_test-model-fast_t0.0"


def test_duplicate_registration_raises(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
) -> None:
    reg = AgentRegistry()
    reg.register_agent("joke", minimal_agent, fast_model)
    with pytest.raises(ValueError, match="already registered"):
        reg.register_agent("joke", minimal_agent, fast_model)


def test_template_and_config_roundtrip(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    slow_model: ModelParameters,
) -> None:
    reg = AgentRegistry()
    fast_id = reg.register_agent("joke", minimal_agent, fast_model)
    slow_id = reg.register_agent("joke", minimal_agent, slow_model)

    template = TemplateTree(
        name="comedy",
        slots=[
            TemplateSlot(name="primary", default_agent_id=fast_id),
            TemplateSlot(name="reviewer", default_agent_id=slow_id),
        ],
    )
    reg.register_template(template)

    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="comedy"),
    )

    resolved = reg.resolve_config("prod")
    assert set(resolved.keys()) == {"primary", "reviewer"}
    assert resolved["primary"].model_parameters.model_name == "test-model-fast"
    assert resolved["reviewer"].model_parameters.model_name == "test-model-slow"
    # Slot named "primary" gets primary mode; others get subagent mode.
    assert resolved["primary"].agent_mode == "primary"
    assert resolved["reviewer"].agent_mode == "subagent"


def test_wildcard_slot_override_resolves_to_match(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
    slow_model: ModelParameters,
) -> None:
    reg = AgentRegistry()
    reg.register_agent("joke", minimal_agent, fast_model)
    reg.register_agent("joke", minimal_agent, slow_model)

    template = TemplateTree(
        name="comedy",
        slots=[TemplateSlot(name="primary", default_agent_id="joke_test-model-fast_t0.0")],
    )
    reg.register_template(template)

    reg.create_compilation_config(
        CompilationConfig(
            name="any_temp",
            template_name="comedy",
            slot_overrides={"primary": "joke_test-model-*"},
        ),
    )
    resolved = reg.resolve_config("any_temp")
    assert "primary" in resolved
    assert resolved["primary"].model_parameters.model_name.startswith("test-model-")


def test_missing_template_raises(
    minimal_agent: AgentDefinition,
    fast_model: ModelParameters,
) -> None:
    reg = AgentRegistry()
    reg.register_agent("joke", minimal_agent, fast_model)
    with pytest.raises(ValueError, match="Template 'nope' not found"):
        reg.create_compilation_config(
            CompilationConfig(name="bad", template_name="nope"),
        )


# ---- register_with_improvements ----------------------------------------


def test_register_with_improvements_no_op_when_no_promotion(
    tmp_path,
    fast_model: ModelParameters,
) -> None:
    """Fresh project → baseline registered unchanged."""
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="improver", name="improver", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="baseline-prompt",
    )
    agent_id = reg.register_with_improvements(
        "improver", agent, fast_model,
        project_root=tmp_path,
    )
    variant = reg.get_agent(agent_id)
    assert variant is not None
    assert variant.agent_definition.system_prompt == "baseline-prompt"


def test_register_with_improvements_applies_promoted_prompt(
    tmp_path,
    fast_model: ModelParameters,
) -> None:
    """When a promotion exists, registration uses the improved version."""
    from open_agent_compiler.improvement.snapshot import promote, write_snapshot
    from open_agent_compiler.improvement.version import ComponentVersion

    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="improver", kind="agent",
                definition={"system_prompt": "promoted-prompt"},
                metrics={},
            ),
            tmp_path / "imp",
        ),
        tmp_path,
    )
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="improver", name="improver", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="baseline-prompt",
    )
    agent_id = reg.register_with_improvements(
        "improver", agent, fast_model,
        project_root=tmp_path,
    )
    assert (
        reg.get_agent(agent_id).agent_definition.system_prompt
        == "promoted-prompt"
    )


def test_register_with_improvements_picks_per_class_slot(
    tmp_path,
    fast_model: ModelParameters,
) -> None:
    """Per-class promotion overrides default when model_class matches."""
    from open_agent_compiler.improvement.snapshot import promote, write_snapshot
    from open_agent_compiler.improvement.version import ComponentVersion

    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="improver", kind="agent",
                definition={"system_prompt": "default-version"},
                metrics={},
            ),
            tmp_path / "a",
        ),
        tmp_path,
    )
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="improver", kind="agent",
                definition={"system_prompt": "fast-version"},
                metrics={},
            ),
            tmp_path / "b",
        ),
        tmp_path,
        model_class="fast",
    )
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(
            agent_id="improver", name="improver", description=None,
        ),
        usage_explanation_long="l", usage_explanation_short="s",
        system_prompt="baseline",
    )
    agent_id = reg.register_with_improvements(
        "improver", agent, fast_model,
        project_root=tmp_path, model_class="fast",
    )
    assert (
        reg.get_agent(agent_id).agent_definition.system_prompt
        == "fast-version"
    )


def test_register_with_improvements_picks_client_bucket(
    tmp_path,
    fast_model: ModelParameters,
) -> None:
    """A client_id loop reads its own bucket; base build ignores it."""
    from open_agent_compiler.improvement.snapshot import promote, write_snapshot
    from open_agent_compiler.improvement.version import ComponentVersion

    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="improver", kind="agent",
                definition={"system_prompt": "base-version"}, metrics={},
            ),
            tmp_path / "a",
        ),
        tmp_path,
    )
    promote(
        write_snapshot(
            ComponentVersion.of(
                component_id="improver", kind="agent",
                definition={"system_prompt": "acme-version"}, metrics={},
            ),
            tmp_path / "b",
        ),
        tmp_path,
        client_id="acme",
    )

    def _baseline() -> AgentDefinition:
        return AgentDefinition(
            header=AgentHeader(
                agent_id="improver", name="improver", description=None,
            ),
            usage_explanation_long="l", usage_explanation_short="s",
            system_prompt="baseline",
        )

    # Client compile picks the client bucket.
    reg_c = AgentRegistry()
    cid = reg_c.register_with_improvements(
        "improver", _baseline(), fast_model,
        project_root=tmp_path, client_id="acme",
    )
    assert (
        reg_c.get_agent(cid).agent_definition.system_prompt == "acme-version"
    )

    # Base compile (client_id=None) inherits the shared base bucket.
    reg_b = AgentRegistry()
    bid = reg_b.register_with_improvements(
        "improver", _baseline(), fast_model, project_root=tmp_path,
    )
    assert (
        reg_b.get_agent(bid).agent_definition.system_prompt == "base-version"
    )
