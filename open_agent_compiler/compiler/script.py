"""CompileScript — Python-side composable replacement for compile.sh.

Users (and the CLI) describe a compile invocation as a Pydantic model
instead of a bash script. The model carries every flag the compiler
respects today; later phases (1.x, 2.x) extend the field set without
changing the call site.

Example:
    script = CompileScript(
        target=Path("./build"),
        factory=my_module.my_registry_factory,
        config="prod",
        clean=True,
    )
    result = script.run()
    print(result.written_files)

The CLI's `compile` subcommand is a thin adapter that builds a
CompileScript from argparse and calls .run().
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Callable, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from open_agent_compiler.compiler.compile import build, build_variant
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.compilation_context import (
    CompilationContext,
    active as active_context,
)
from open_agent_compiler.model.core.variant_spec import VariantSpec

Factory = Callable[[], AgentRegistry]
CleanStrategy = Literal["none", "full", "per_variant"]


class CompileResult(BaseModel):
    """Structured outcome of one CompileScript.run() call."""

    target: Path
    config: str
    resolved_slots: list[str] = Field(default_factory=list)
    written_files: list[Path] = Field(default_factory=list)
    dry_run: bool = False
    variants: list[str] = Field(
        default_factory=list,
        description="Names of VariantSpecs that contributed to this build.",
    )


class CompileScript(BaseModel):
    """A composable compile invocation.

    Either `factory` (a callable returning an AgentRegistry) or
    `factory_spec` (a 'module:callable' string the CLI uses) must be
    provided. Passing both is an error; passing neither is also an error.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    target: Path
    config: str
    dialect: str = Field(
        default="opencode",
        description="Dialect name registered in open_agent_compiler.compiler.dialects.",
    )
    factory: Factory | None = None
    factory_spec: str | None = None
    clean: bool = False
    clean_strategy: CleanStrategy | None = Field(
        default=None,
        description=(
            "'full' wipes the entire target before any pass. 'per_variant'"
            " removes only files whose name carries this variant's postfix"
            " before that variant writes. 'none' touches nothing existing."
            " When unset, defaults to 'full' if clean=True else 'none'."
        ),
    )
    dry_run: bool = False
    verbose: bool = False
    variants: list[VariantSpec] | None = Field(
        default=None,
        description=(
            "If set, compile once per spec applying each variant's preset"
            " + postfix. None = single-pass legacy behavior using the"
            " presets bound at registration."
        ),
    )
    access_profile: str | None = Field(
        default=None,
        description=(
            "Name of the AccessProfile flowed into the CompilationContext"
            " for every variant pass. Visible to factories via"
            " current_context().access_profile_name."
        ),
    )
    mock_profile: str | None = Field(
        default=None,
        description="Name of the MockProfile flowed into the CompilationContext.",
    )
    client_id: str | None = Field(
        default=None,
        description=(
            "Tenant this compile is personalized for. Flowed into the"
            " CompilationContext for every variant pass so factories (and"
            " register_with_improvements) read the per-client promotion"
            " bucket. None = the base, single-tenant build (unchanged)."
        ),
    )
    native_tools: bool = Field(
        default=False,
        description=(
            "Emit the harness's NATIVE tool-calling form for json-contract"
            " tools alongside the bash docs: .opencode/tool/<name>.ts shims"
            " (opencode), an MCP tools server + .mcp.json (claude) or"
            " [mcp_servers] blocks (codex). See compiler/native_tools.py."
        ),
    )
    store_url: str | None = Field(
        default=None,
        description=(
            "Run-store connection URL (e.g. 'sqlite:///.oac/improvement.db')."
            " When set, the compile's artifacts (dialect, config, written"
            " files) are recorded in the store's compiles table so builds"
            " are traceable next to the improvement runs that shaped them."
        ),
    )

    @model_validator(mode="after")
    def _dialect_is_registered(self) -> Self:
        # Imported lazily to avoid loading the dialect registry at module
        # import time (it pulls in the OpenCode compiler which has deps).
        from open_agent_compiler.compiler.dialects import list_dialects
        if self.dialect not in list_dialects():
            raise ValueError(
                f"unknown dialect {self.dialect!r}; registered:"
                f" {list_dialects()}"
            )
        return self

    @model_validator(mode="after")
    def _exactly_one_factory(self) -> Self:
        if (self.factory is None) == (self.factory_spec is None):
            raise ValueError(
                "CompileScript needs exactly one of `factory` or `factory_spec`."
            )
        return self

    @model_validator(mode="after")
    def _no_postfix_collision_across_variants(self) -> Self:
        if not self.variants:
            return self
        seen: dict[str, str] = {}
        for spec in self.variants:
            other = seen.get(spec.postfix)
            if other is not None:
                raise ValueError(
                    f"Two variants share postfix {spec.postfix!r}:"
                    f" {other!r} and {spec.name!r}."
                    f" Variants must use distinct postfixes — they would"
                    f" overwrite each other's compiled artifacts."
                )
            seen[spec.postfix] = spec.name
        return self

    def effective_clean_strategy(self) -> CleanStrategy:
        if self.clean_strategy is not None:
            return self.clean_strategy
        return "full" if self.clean else "none"

    def resolve_factory(self) -> Factory:
        if self.factory is not None:
            return self.factory
        spec = self.factory_spec
        assert spec is not None  # validator guarantees this
        if ":" not in spec:
            raise ValueError(
                f"factory_spec must be 'module:callable', got {spec!r}"
            )
        module_name, attr = spec.rsplit(":", 1)
        # Mirror `python -m` semantics: resolve specs like
        # "agents:registry" from the invoking project's root without
        # requiring the project to be installed.
        cwd = str(Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        module = importlib.import_module(module_name)
        factory = getattr(module, attr, None)
        if factory is None:
            raise ValueError(f"{module_name} has no attribute {attr!r}")
        if not callable(factory):
            raise ValueError(f"{spec} is not callable")
        return factory

    def _prepare_target(self) -> None:
        if self.effective_clean_strategy() == "full" and self.target.exists():
            shutil.rmtree(self.target)
        self.target.mkdir(parents=True, exist_ok=True)

    def _clean_variant_artifacts(self, postfix: str) -> None:
        """Remove files whose stem carries this variant's postfix.

        Empty postfix means "the default variant" — we conservatively skip
        cleaning under per_variant mode there, otherwise we'd delete every
        compiled file (every file's stem trivially ends with "").
        """
        if not postfix or not self.target.exists():
            return
        # Compiled artifacts use postfix as a suffix on the stem
        # (e.g. agent_primary-glm47.md). Match those exactly.
        for path in self.target.rglob("*"):
            if not path.is_file():
                continue
            if path.stem.endswith(postfix):
                path.unlink()

    def run(self) -> CompileResult:
        factory = self.resolve_factory()

        # A throwaway pass under the default context so dry-run / single-pass
        # callers don't pay the cost of re-building the registry per variant.
        with active_context(CompilationContext()):
            base_registry = factory()
            resolved = base_registry.resolve_config(self.config)

        if self.dry_run:
            if self.verbose:
                variant_count = len(self.variants) if self.variants else 1
                print(
                    f"[oac compile dry-run] would compile {len(resolved)} slot(s) "
                    f"x {variant_count} variant(s) -> {self.target}"
                )
            return CompileResult(
                target=self.target,
                config=self.config,
                resolved_slots=sorted(resolved.keys()),
                variants=[v.name for v in (self.variants or [])],
                dry_run=True,
            )

        before = self._snapshot()
        self._prepare_target()
        strategy = self.effective_clean_strategy()
        if self.variants:
            for spec in self.variants:
                if strategy == "per_variant":
                    self._clean_variant_artifacts(spec.postfix)
                ctx = CompilationContext(
                    variant_name=spec.name,
                    variant_postfix=spec.postfix,
                    access_profile_name=self.access_profile,
                    mock_profile_name=self.mock_profile,
                    client_id=self.client_id,
                    feature_flags=spec.feature_flags,
                )
                with active_context(ctx):
                    # Re-call the factory under the active context so agent
                    # definitions that branch on current_context() see the
                    # right values for this variant.
                    variant_registry = factory()
                    build_variant(
                        self.target, variant_registry, self.config, spec,
                        access_profile_name=self.access_profile,
                        mock_profile_name=self.mock_profile,
                        client_id=self.client_id,
                        dialect=self.dialect,
                        options={"native_tools": self.native_tools},
                    )
        else:
            build(
                self.target, base_registry, self.config, dialect=self.dialect,
                options={"native_tools": self.native_tools},
            )
        after = self._snapshot()
        written = sorted(after - before)

        if self.verbose:
            n_variants = len(self.variants) if self.variants else 1
            print(
                f"[oac compile] wrote {len(written)} file(s) for {n_variants}"
                f" variant(s) to {self.target}"
            )

        if self.store_url and not self.dry_run:
            from open_agent_compiler.improvement.store import open_store
            store = open_store(self.store_url)
            record = getattr(store, "record_compile", None)
            if record is not None:
                record(
                    target=str(self.target),
                    dialect=self.dialect,
                    config=self.config,
                    variants=[v.name for v in (self.variants or [])],
                    files=[str(p) for p in written],
                )

        return CompileResult(
            target=self.target,
            config=self.config,
            resolved_slots=sorted(resolved.keys()),
            written_files=written,
            variants=[v.name for v in (self.variants or [])],
        )

    def _snapshot(self) -> set[Path]:
        if not self.target.exists():
            return set()
        return {p for p in self.target.rglob("*") if p.is_file()}
