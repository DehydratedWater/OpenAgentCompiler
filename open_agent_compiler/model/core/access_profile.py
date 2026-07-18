"""AccessProfile — bind symbolic resource names to concrete adapters.

A tool that touches an external system (a database, an API, the
filesystem, an MCP server, …) declares the resources it needs by name:

    ToolDefinition(
        header=...,
        requires_resources=["goal_db", "telegram_bot"],
        ...
    )

An AccessProfile carries the bindings the compiler should wire in:

    prod = AccessProfile(
        name="prod",
        bindings={
            "goal_db": ResourceBinding(kind="postgres", config={"dsn": "..."}),
            "telegram_bot": ResourceBinding(kind="api", config={"token": "..."}),
        },
    )

The compile invocation picks one profile per compilation pass. The
compiler validates that every required resource is bound (or marked
mock_only with a MockProfile covering it) before emitting artifacts.

Profiles compose via `extends`:

    test_isolated = AccessProfile(
        name="test-isolated",
        extends="prod",
        bindings={
            "goal_db": ResourceBinding(
                kind="sqlite", config={"path": ":memory:"}
            ),
            # telegram_bot inherits from "prod"
        },
    )

Inheritance is single-parent — multi-parent merging is intentionally
not supported (the ordering ambiguity isn't worth the rare convenience).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResourceKind = Literal[
    "api",
    "postgres",
    "sqlite",
    "mysql",
    "redis",
    "fs",
    "mcp",
    "vector_store",
    "queue",
    "websocket",
    "vllm",
    "anthropic",
    "openai",
    "other",
]


class ResourceBinding(BaseModel):
    """How a single resource is wired up under one AccessProfile.

    config is intentionally a free-form dict — different adapters need
    different fields (DSN vs base_url vs token). Concrete tool runtimes
    interpret it; the compiler treats it as opaque data to pass through.
    """

    model_config = ConfigDict(frozen=True)

    kind: ResourceKind
    config: dict[str, Any] = Field(default_factory=dict)
    mock_only: bool = Field(
        default=False,
        description=(
            "If True, this resource is unusable without an active MockProfile"
            " supplying responses for every tool that requires it. The"
            " compiler rejects compile passes that violate this."
        ),
    )
    description: str | None = None


class AccessProfile(BaseModel):
    """A named map of resource bindings selectable at compile time."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    extends: str | None = Field(
        default=None,
        description="Name of another AccessProfile to inherit bindings from.",
    )
    bindings: dict[str, ResourceBinding] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _name_is_non_empty(self) -> "AccessProfile":
        if not self.name.strip():
            raise ValueError("AccessProfile.name must be non-empty")
        return self


class AccessProfileRegistry(BaseModel):
    """Lookup container for AccessProfiles that supports inheritance.

    Kept separate from AgentRegistry so users can ship a profile set
    independently of an agent set (and vice versa).
    """

    model_config = ConfigDict(frozen=False)

    profiles: dict[str, AccessProfile] = Field(default_factory=dict)

    def register(self, profile: AccessProfile) -> None:
        if profile.name in self.profiles:
            raise ValueError(f"AccessProfile {profile.name!r} already registered")
        if profile.extends and profile.extends not in self.profiles:
            raise ValueError(
                f"AccessProfile {profile.name!r} extends "
                f"{profile.extends!r} which is not registered"
            )
        self.profiles[profile.name] = profile

    def get(self, name: str) -> AccessProfile | None:
        return self.profiles.get(name)

    def resolve(self, name: str) -> dict[str, ResourceBinding]:
        """Return the effective bindings for `name`, walking `extends` chains.

        Child bindings shadow parents. Cycles raise ValueError.
        """
        seen: list[str] = []
        cursor = self.profiles.get(name)
        if cursor is None:
            raise ValueError(f"AccessProfile {name!r} not registered")
        chain: list[AccessProfile] = []
        while cursor is not None:
            if cursor.name in seen:
                raise ValueError(
                    f"Cyclic AccessProfile inheritance: {' -> '.join(seen + [cursor.name])}"
                )
            seen.append(cursor.name)
            chain.append(cursor)
            if cursor.extends is None:
                break
            cursor = self.profiles.get(cursor.extends)
            if cursor is None:
                raise ValueError(
                    f"AccessProfile {chain[-1].name!r} extends "
                    f"{chain[-1].extends!r} which is not registered"
                )

        # Walk parent -> child so child bindings overwrite parents.
        effective: dict[str, ResourceBinding] = {}
        for profile in reversed(chain):
            effective.update(profile.bindings)
        return effective

    def validate_against(
        self,
        profile_name: str,
        tool_requirements: dict[str, list[str]],
        mock_covered: set[str] | None = None,
    ) -> None:
        """Ensure every required resource for every tool is satisfied.

        Args:
            profile_name: the active AccessProfile.
            tool_requirements: mapping of tool name → list of resource names.
            mock_covered: names of tools fully covered by an active
                MockProfile. mock_only resources for those tools are
                acceptable; for any other tool they raise.
        """
        effective = self.resolve(profile_name)
        mock_covered = mock_covered or set()
        problems: list[str] = []
        for tool_name, needed in tool_requirements.items():
            for resource_name in needed:
                binding = effective.get(resource_name)
                if binding is None:
                    problems.append(
                        f"tool {tool_name!r} requires resource {resource_name!r}"
                        f" but AccessProfile {profile_name!r} has no binding for it"
                    )
                    continue
                if binding.mock_only and tool_name not in mock_covered:
                    problems.append(
                        f"tool {tool_name!r} uses resource {resource_name!r}"
                        f" which is mock_only under AccessProfile {profile_name!r},"
                        f" but no active MockProfile covers this tool"
                    )
        if problems:
            raise ValueError(
                "AccessProfile validation failed:\n  - "
                + "\n  - ".join(problems)
            )
