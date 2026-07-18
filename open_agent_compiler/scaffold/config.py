"""ScaffoldConfig — the input contract for `oac init`.

All knobs the user can flip via CLI flags or interactive prompts land
here as Pydantic fields with sensible defaults. The engine reads this
config and decides which generators to invoke.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Template = Literal["barebones", "web", "full", "saas-personalized"]
LLMProvider = Literal[
    "anthropic", "openai", "openrouter", "vllm", "zai-coding-plan",
]
Observability = Literal["none", "langfuse"]
ProxyKind = Literal["none", "nginx", "traefik"]


class ScaffoldConfig(BaseModel):
    """Resolved configuration passed to ScaffoldEngine."""

    model_config = ConfigDict(frozen=True)

    target: Path
    project_name: str = "oac-project"
    template: Template = "web"
    llm: LLMProvider = "anthropic"
    dialect: str = Field(
        default="opencode",
        description=(
            "Output dialect the generated build_agents.py compiles to."
            " Validated against the dialect registry at scaffold time"
            " (opencode, claude, pi, or an externally registered one)."
        ),
    )

    with_postgres: bool = False
    with_sqlite: bool = False
    with_redis: bool = False
    with_qdrant: bool = False
    with_ollama: bool = False
    with_mcp_server: bool = Field(
        default=False,
        description=(
            "Expose the compiled agents as MCP tools alongside the"
            " FastAPI REST API. Generates app/mcp_server.py +"
            " mcp_server_run.py; each agent becomes one MCP tool"
            " whose arguments mirror AgentRunRequest."
        ),
    )
    uv_sync: bool = Field(
        default=False,
        description=(
            "When True, run `uv sync` in the target directory after"
            " scaffolding so dependencies install automatically."
            " Defaults False at the model level so unit tests don't"
            " incur a sync per scaffold; the `oac init` CLI flips it"
            " to True by default (override with --no-uv-sync)."
        ),
    )
    observability: Observability = "none"
    proxy: ProxyKind = "none"
    with_telegram_bot: bool = False
    with_cron: bool = False
    cron_events_path: Path = Path("cron/events.json")
    skills: tuple[str, ...] = Field(
        default=(),
        description=(
            "Dialect targets to emit developer skills for. Subset of"
            " ('opencode', 'claude'). Empty tuple = no skills emitted."
        ),
    )

    force_overwrite: bool = Field(
        default=False,
        description=(
            "When False (default), the engine refuses to write into a"
            " non-empty target directory. Set True to refresh"
            " framework-owned files (those whose sha256 matches the"
            " recorded manifest from the prior scaffold) — user-edited"
            " files are PRESERVED. Set force_overwrite_all for the"
            " destructive 'replace everything' behaviour."
        ),
    )
    force_overwrite_all: bool = Field(
        default=False,
        description=(
            "When True, overwrite EVERY scaffold file unconditionally,"
            " including user-edited ones. Implies force_overwrite=True."
            " Use only when you really want to nuke local changes."
        ),
    )

    @property
    def has_web_app(self) -> bool:
        """Templates that emit the FastAPI `app/` service.

        `saas-personalized` is a web-shaped template (its per-client flow is
        served over HTTP), so it inherits every web/full generator gate.
        """
        return self.template in ("web", "full", "saas-personalized")

    @property
    def is_personalized(self) -> bool:
        """The per-client auto-optimization SaaS template (Phase F)."""
        return self.template == "saas-personalized"

    @model_validator(mode="before")
    @classmethod
    def _full_template_implies_postgres(cls, data):
        """The 'full' template includes a DB; auto-toggle postgres.

        Runs in 'before' mode so the change is applied to the input dict
        before the frozen model is constructed — 'after' mode can't return
        a different instance.
        """
        if not isinstance(data, dict):
            return data
        if data.get("template") == "full" and not data.get("with_postgres", False):
            data = {**data, "with_postgres": True}
        return data

    @model_validator(mode="before")
    @classmethod
    def _overwrite_all_implies_overwrite(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("force_overwrite_all") and not data.get("force_overwrite"):
            data = {**data, "force_overwrite": True}
        return data

    @model_validator(mode="after")
    def _project_name_is_slug_like(self) -> "ScaffoldConfig":
        if not self.project_name or any(
            c.isspace() or c in "/\\:" for c in self.project_name
        ):
            raise ValueError(
                f"project_name {self.project_name!r} contains invalid characters"
            )
        return self
