from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentVariant,
    CompilationConfig,
    ModelParameters,
    TemplateTree,
)
from open_agent_compiler.model.core.mock_model import MockProfile
from open_agent_compiler.model.core.model_preset import ModelPreset


def _generate_agent_id(name: str, model_params: ModelParameters, preset_name: str | None = None) -> str:
    """Stable id derived from (logical name, model id, temperature, preset).

    If `preset_name` is supplied it is used in place of the model id —
    this lets two presets sharing the same model_id (different sampling
    or provider routing) still produce distinct agent_ids, which is
    required for multi-variant compilation in Phase 2.1.
    """
    discriminator = preset_name or model_params.model_name
    model = re.sub(r"[^a-zA-Z0-9\-.]", "_", discriminator)
    temp = str(model_params.temperature) if model_params.temperature is not None else "None"
    return f"{name}_{model}_t{temp}"


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentVariant] = {}
        self._templates: dict[str, TemplateTree] = {}
        self._configs: dict[str, CompilationConfig] = {}
        self._presets: dict[str, ModelPreset] = {}
        self._agent_presets: dict[str, str | None] = {}
        self._mock_profiles: dict[str, MockProfile] = {}

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(
        self,
        name: str,
        agent_definition: AgentDefinition,
        model_parameters: ModelParameters,
    ) -> str:
        agent_id = _generate_agent_id(name, model_parameters)

        if agent_id in self._agents:
            raise ValueError(f"Agent ID '{agent_id}' already registered")

        variant = AgentVariant(
            postfix="",
            agent_mode="primary",
            agent_definition=agent_definition,
            model_parameters=model_parameters,
        )
        self._agents[agent_id] = variant
        self._agent_presets[agent_id] = None
        return agent_id

    def register_with_improvements(
        self,
        name: str,
        agent_definition: AgentDefinition,
        model_parameters: ModelParameters,
        *,
        project_root: Path | None = None,
        model_class: str | None = None,
        client_id: str | None = None,
    ) -> str:
        """Register an agent after auto-applying promoted improvements.

        Walks the AgentDefinition tree (the agent itself, its skills,
        and its `extra_tools`) and merges any promoted snapshots into
        the baseline before registration. If a component has no
        promoted snapshot the baseline passes through unchanged, so the
        same call works on a fresh project and on a project with
        partial / full improvements promoted.

        `model_class` picks the per-class snapshot slot with a
        fallback to the default slot, matching the resolution order
        documented in `open_agent_compiler/improvement/snapshot.py`. Pass the model
        class the agent will run under (e.g. 'fast' / 'analytical' /
        'local') to load class-specific tuning.

        `client_id` selects the per-client promotion bucket with a
        fallback to the shared base bucket — a client's compile reads
        its own promotions and inherits base tuning for anything it
        hasn't personalized. client_id=None is the base build.

        Subagents (which are AgentHeader *references* rather than full
        AgentDefinitions) are not walked here; call this same helper
        when registering each one so the whole composition uses
        improvements transparently.
        """
        # Local import to avoid circular import between agent_registry
        # and the improvement package (which itself imports agent
        # models for typing).
        from open_agent_compiler.improvement.snapshot import apply_promoted_to_tree
        improved = apply_promoted_to_tree(
            agent_definition,
            project_root=project_root,
            model_class=model_class,
            client_id=client_id,
        )
        return self.register_agent(name, improved, model_parameters)

    def register_agent_with_preset(
        self,
        name: str,
        agent_definition: AgentDefinition,
        preset: ModelPreset,
    ) -> str:
        """Register an agent bound to a rich ModelPreset.

        Two presets with the same model_id but different sampling or
        provider routing still produce distinct agent_ids because the
        preset name participates in the discriminator.
        """
        if preset.name not in self._presets:
            self._presets[preset.name] = preset
        elif self._presets[preset.name] != preset:
            raise ValueError(
                f"ModelPreset {preset.name!r} already registered with different config"
            )
        params = preset.to_model_parameters()
        agent_id = _generate_agent_id(name, params, preset_name=preset.name)
        if agent_id in self._agents:
            raise ValueError(f"Agent ID '{agent_id}' already registered")
        variant = AgentVariant(
            postfix="",
            agent_mode="primary",
            agent_definition=agent_definition,
            model_parameters=params,
        )
        self._agents[agent_id] = variant
        self._agent_presets[agent_id] = preset.name
        return agent_id

    def get_preset(self, name: str) -> ModelPreset | None:
        return self._presets.get(name)

    def list_presets(self) -> list[str]:
        return list(self._presets.keys())

    def preset_for(self, agent_id: str) -> ModelPreset | None:
        """Return the ModelPreset bound to `agent_id`, or None for legacy registrations."""
        preset_name = self._agent_presets.get(agent_id)
        if preset_name is None:
            return None
        return self._presets.get(preset_name)

    # ------------------------------------------------------------------
    # Mock profile registry (used by the testing framework)
    # ------------------------------------------------------------------

    def register_mock_profile(self, profile: MockProfile) -> None:
        """Register a MockProfile that tests can bind by name."""
        if profile.name in self._mock_profiles:
            raise ValueError(
                f"MockProfile {profile.name!r} already registered"
            )
        self._mock_profiles[profile.name] = profile

    def get_mock_profile(self, name: str) -> MockProfile | None:
        return self._mock_profiles.get(name)

    def list_mock_profiles(self) -> list[str]:
        return list(self._mock_profiles.keys())

    def get_agent(self, agent_id: str) -> AgentVariant | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Template registration
    # ------------------------------------------------------------------

    def register_template(self, template_tree: TemplateTree) -> None:
        if template_tree.name in self._templates:
            raise ValueError(f"Template '{template_tree.name}' already registered")
        self._templates[template_tree.name] = template_tree

    def get_template(self, name: str) -> TemplateTree | None:
        return self._templates.get(name)

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())

    # ------------------------------------------------------------------
    # Compilation config
    # ------------------------------------------------------------------

    def create_compilation_config(self, config: CompilationConfig) -> None:
        if config.name in self._configs:
            raise ValueError(f"Config '{config.name}' already registered")

        if config.strict_validation:
            self._validate_config(config)

        self._configs[config.name] = config

    def _validate_config(self, config: CompilationConfig) -> None:
        template = self._templates.get(config.template_name)
        if template is None:
            raise ValueError(
                f"Template '{config.template_name}' not found for config '{config.name}'"
            )

        for slot in template.slots:
            agent_id = config.slot_overrides.get(slot.name, slot.default_agent_id)
            if "*" in agent_id:
                matches = self._match_wildcard(agent_id)
                if not matches:
                    raise ValueError(
                        f"No agent matches wildcard '{agent_id}' for slot '{slot.name}' "
                        f"in config '{config.name}'"
                    )
            elif agent_id not in self._agents:
                raise ValueError(
                    f"Agent ID '{agent_id}' not found for slot '{slot.name}' "
                    f"in config '{config.name}'"
                )

    def _match_wildcard(self, pattern: str) -> list[str]:
        return [aid for aid in self._agents if fnmatch(aid, pattern)]

    def get_config(self, name: str) -> CompilationConfig | None:
        return self._configs.get(name)

    def list_configs(self) -> list[str]:
        return list(self._configs.keys())

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_config(self, config_name: str) -> dict[str, AgentVariant]:
        config = self._configs.get(config_name)
        if config is None:
            raise ValueError(f"Config '{config_name}' not found")

        template = self._templates.get(config.template_name)
        if template is None:
            raise ValueError(
                f"Template '{config.template_name}' not found for config '{config_name}'"
            )

        resolved: dict[str, AgentVariant] = {}

        for slot in template.slots:
            agent_id = config.slot_overrides.get(slot.name, slot.default_agent_id)

            if "*" in agent_id:
                matches = self._match_wildcard(agent_id)
                if not matches:
                    raise ValueError(
                        f"No agent matches wildcard '{agent_id}' for slot '{slot.name}' "
                        f"in config '{config_name}'"
                    )
                agent_id = matches[0]

            variant = self._agents.get(agent_id)
            if variant is None:
                raise ValueError(
                    f"Agent ID '{agent_id}' not found for slot '{slot.name}' "
                    f"in config '{config_name}'"
                )

            # Create a copy with the config's postfix and appropriate mode.
            # Propagate the slot's also_compile_as_primary flag onto the
            # variant so the compiler can emit the second .md.
            variant_copy = variant.model_copy()
            variant_copy.postfix = config.postfix
            variant_copy.agent_mode = "primary" if slot.name == "primary" else "subagent"
            variant_copy.also_compile_as_primary = slot.also_compile_as_primary

            resolved[slot.name] = variant_copy

        return resolved
