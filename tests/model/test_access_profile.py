"""AccessProfile + ResourceBinding + AccessProfileRegistry."""

from __future__ import annotations

import pytest

from open_agent_compiler.model.core.access_profile import (
    AccessProfile,
    AccessProfileRegistry,
    ResourceBinding,
)


def _binding(**kw) -> ResourceBinding:
    return ResourceBinding(kind=kw.pop("kind", "api"), **kw)


def test_register_rejects_extends_unknown_parent() -> None:
    reg = AccessProfileRegistry()
    child = AccessProfile(name="child", extends="ghost", bindings={})
    with pytest.raises(ValueError, match="extends 'ghost'"):
        reg.register(child)


def test_register_rejects_duplicate_name() -> None:
    reg = AccessProfileRegistry()
    reg.register(AccessProfile(name="p", bindings={}))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(AccessProfile(name="p", bindings={}))


def test_resolve_walks_inheritance_chain_child_shadows_parent() -> None:
    reg = AccessProfileRegistry()
    reg.register(
        AccessProfile(
            name="prod",
            bindings={
                "db": _binding(kind="postgres", config={"dsn": "prod-dsn"}),
                "bot": _binding(kind="api", config={"token": "prod-token"}),
            },
        )
    )
    reg.register(
        AccessProfile(
            name="test",
            extends="prod",
            bindings={"db": _binding(kind="sqlite", config={"path": ":memory:"})},
        )
    )
    effective = reg.resolve("test")
    assert effective["db"].kind == "sqlite"
    assert effective["db"].config == {"path": ":memory:"}
    # bot inherited
    assert effective["bot"].config == {"token": "prod-token"}


def test_resolve_detects_cycle() -> None:
    # Build a cycle by bypassing the register-time parent check.
    reg = AccessProfileRegistry()
    reg.profiles["a"] = AccessProfile(name="a", extends="b", bindings={})
    reg.profiles["b"] = AccessProfile(name="b", extends="a", bindings={})
    with pytest.raises(ValueError, match="Cyclic AccessProfile inheritance"):
        reg.resolve("a")


def test_validate_against_passes_when_every_resource_is_bound() -> None:
    reg = AccessProfileRegistry()
    reg.register(
        AccessProfile(
            name="prod",
            bindings={"db": _binding(kind="postgres", config={})},
        )
    )
    reg.validate_against("prod", {"goal-getter": ["db"]})


def test_validate_against_reports_every_missing_resource() -> None:
    reg = AccessProfileRegistry()
    reg.register(AccessProfile(name="prod", bindings={}))
    with pytest.raises(ValueError) as exc:
        reg.validate_against(
            "prod",
            {"a": ["db"], "b": ["queue", "telegram_bot"]},
        )
    msg = str(exc.value)
    assert "tool 'a' requires resource 'db'" in msg
    assert "tool 'b' requires resource 'queue'" in msg
    assert "tool 'b' requires resource 'telegram_bot'" in msg


def test_mock_only_resource_rejects_uncovered_tool() -> None:
    reg = AccessProfileRegistry()
    reg.register(
        AccessProfile(
            name="ci",
            bindings={
                "telegram_bot": _binding(
                    kind="api", config={}, mock_only=True
                ),
            },
        )
    )
    with pytest.raises(ValueError, match="mock_only"):
        reg.validate_against("ci", {"send-message": ["telegram_bot"]})


def test_mock_only_resource_passes_when_tool_is_mock_covered() -> None:
    reg = AccessProfileRegistry()
    reg.register(
        AccessProfile(
            name="ci",
            bindings={
                "telegram_bot": _binding(
                    kind="api", config={}, mock_only=True
                ),
            },
        )
    )
    reg.validate_against(
        "ci",
        {"send-message": ["telegram_bot"]},
        mock_covered={"send-message"},
    )


def test_empty_profile_name_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        AccessProfile(name="   ", bindings={})


def test_tool_definition_can_declare_requires_resources() -> None:
    from open_agent_compiler.model.core.permissions_model import BashToolPermission
    from open_agent_compiler.model.core.tools_model import (
        ToolDefinition,
        ToolDefinitionHeader,
        ToolDefinitionLogicBash,
    )

    t = ToolDefinition(
        header=ToolDefinitionHeader(
            name="goal-getter",
            description="reads a goal",
            usage_explanation_long="long",
            usage_explanation_short="short",
            rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(tool_name="bash", value="allow"),
            positive_examples=[], negative_examples=[], mode_specific_rules=[],
        ),
        requires_resources=["goal_db"],
    )
    assert t.requires_resources == ["goal_db"]
