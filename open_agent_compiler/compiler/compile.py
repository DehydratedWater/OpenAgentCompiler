from pathlib import Path

from open_agent_compiler.compiler.dialects import get as get_dialect
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.compilation_context import (
    CompilationContext,
    active as active_context,
)
from open_agent_compiler.model.core.variant_spec import VariantSpec, apply_variant


def build(
    target: Path,
    registry: AgentRegistry,
    config_name: str,
    *,
    dialect: str = "opencode",
) -> None:
    """Single-pass compile using whatever presets were bound at registration."""
    with active_context(CompilationContext()):
        resolved_variants = registry.resolve_config(config_name)
        dialect_cls = get_dialect(dialect)
        compiler = dialect_cls(target, resolved_variants)
        compiler.compile()


def build_variant(
    target: Path,
    registry: AgentRegistry,
    config_name: str,
    spec: VariantSpec,
    *,
    access_profile_name: str | None = None,
    mock_profile_name: str | None = None,
    client_id: str | None = None,
    dialect: str = "opencode",
) -> None:
    """One pass under `spec`: apply its preset + postfix to every variant.

    The original resolved tree is left untouched (apply_variant returns a
    model_copy), so callers may invoke build_variant multiple times with
    different specs in one session.

    The variant's feature_flags + profile names are pushed into the
    active CompilationContext for the lifetime of the pass — factories
    that read current_context() see them during resolve_config() *and*
    during compile().
    """
    ctx = CompilationContext(
        variant_name=spec.name,
        variant_postfix=spec.postfix,
        access_profile_name=access_profile_name,
        mock_profile_name=mock_profile_name,
        client_id=client_id,
        feature_flags=spec.feature_flags,
    )
    with active_context(ctx):
        resolved = registry.resolve_config(config_name)
        per_variant = {
            slot: apply_variant(spec, variant) for slot, variant in resolved.items()
        }
        dialect_cls = get_dialect(dialect)
        compiler = dialect_cls(target, per_variant)
        compiler.compile()
