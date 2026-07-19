"""Registry of all authored skill bundles."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle
from open_agent_compiler.skills.content import (
    authoring_agents,
    authoring_tools,
    autoloop_interview,
    docker_and_compose,
    dynamic_extractor,
    getting_started,
    improvement_loop,
    interactive_agents,
    optimization_targets,
    project_orchestration,
    prompt_structure,
    providers_and_models,
    sandboxed_scripting,
    tool_variants,
    variants_and_profiles,
    writing_tests,
)

# Each authored skill module exposes a `build() -> SkillBundle` factory.
# Listed in topic order (the user reads them top-down): orientation,
# then methodology, then authoring fundamentals, then operations, meta.
_SKILL_BUILDERS = (
    getting_started.build,
    project_orchestration.build,
    authoring_agents.build,
    authoring_tools.build,
    tool_variants.build,
    prompt_structure.build,
    writing_tests.build,
    providers_and_models.build,
    variants_and_profiles.build,
    docker_and_compose.build,
    improvement_loop.build,
    optimization_targets.build,
    autoloop_interview.build,
    sandboxed_scripting.build,
    dynamic_extractor.build,
    interactive_agents.build,
)


def list_skills() -> list[SkillBundle]:
    """Return every authored SkillBundle freshly built (cheap)."""
    return [build() for build in _SKILL_BUILDERS]


def get_skill(name: str) -> SkillBundle | None:
    for build in _SKILL_BUILDERS:
        bundle = build()
        if bundle.name == name:
            return bundle
    return None
