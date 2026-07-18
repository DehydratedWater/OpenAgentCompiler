"""ScaffoldEngine — write every generator's output to the target directory.

The engine resolves which files to render for the given config + template,
calls each generator in turn, writes the result, and reports back via
ScaffoldResult so the CLI can summarize what happened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.scaffold.config import ScaffoldConfig
from open_agent_compiler.scaffold.files import agents as agents_files
from open_agent_compiler.scaffold.files import app as app_files
from open_agent_compiler.scaffold.files import compose as compose_files
from open_agent_compiler.scaffold.files import cron as cron_files
from open_agent_compiler.scaffold.files import db as db_files
from open_agent_compiler.scaffold.files import dispatch as dispatch_files
from open_agent_compiler.scaffold.files import dockerfile as dockerfile_files
from open_agent_compiler.scaffold.files import env_example, gitignore, pyproject, readme
from open_agent_compiler.scaffold.files import mcp_server as mcp_files
from open_agent_compiler.scaffold.files import personalized as personalized_files
from open_agent_compiler.scaffold.files import runs as runs_files
from open_agent_compiler.scaffold.files import sqlite_tool as sqlite_files
from open_agent_compiler.skills import emit_claude, emit_opencode, list_skills

# A FileGenerator is a callable returning the file's full text content.
FileGenerator = Callable[[ScaffoldConfig], str]


def _file_map(config: ScaffoldConfig) -> dict[str, FileGenerator]:
    """Resolve {relative_path: generator} for the given config."""
    files: dict[str, FileGenerator] = {
        ".gitignore": gitignore.render,
        ".env.example": env_example.render,
        "pyproject.toml": pyproject.render,
        "README.md": readme.render,
        "agents/__init__.py": agents_files.render_package_init,
        "agents/registry.py": agents_files.render_registry,
        "build_agents.py": agents_files.render_build_agents_script,
    }
    if config.has_web_app:
        files.update({
            "docker/Dockerfile": dockerfile_files.render,
            "docker/docker-entrypoint.sh": dockerfile_files.render_entrypoint,
            "docker/docker-compose.yml": compose_files.render,
            "app/__init__.py": app_files.render_app_init,
            "app/main.py": app_files.render_app_main,
            "app/models.py": app_files.render_models,
            "app/agent_runner.py": app_files.render_agent_runner,
            # Phase 23: mode-aware + retry-aware dispatcher.
            "app/dispatch.py": dispatch_files.render_dispatch_module,
            "run.py": app_files.render_run_py,
        })
    if config.with_cron:
        files.update({
            str(config.cron_events_path): cron_files.render_events_json,
            "cron/__init__.py": lambda c: "",
            "cron/driver.py": cron_files.render_driver,
        })
    if config.with_sqlite:
        files.update({
            "tools/__init__.py": lambda c: "",
            "tools/notes_db.py": sqlite_files.render_notes_db_tool,
            "agents/access_profile.py": sqlite_files.render_access_profile,
        })
    if config.with_postgres:
        # Phase 17: full pgvector + Alembic wiring. Even projects that
        # only use postgres for run-tracking get the runs/tool_calls
        # tables out of the box.
        files.update({
            "db/__init__.py": lambda c: "",
            "db/session.py": db_files.render_session_module,
            "db/repositories.py": db_files.render_repositories,
            "alembic.ini": db_files.render_alembic_ini,
            "migrations/env.py": db_files.render_alembic_env,
            "migrations/script.py.mako": db_files.render_alembic_script_template,
            "migrations/versions/001_initial.py": db_files.render_seed_migration,
        })
        if config.has_web_app:
            # Phase 18: run-tracking API endpoints + persistence wrapper.
            # Only emit when both the FastAPI app and the DB are present.
            files.update({
                "app/persistence.py": runs_files.render_persistence_module,
                "app/runs.py": runs_files.render_runs_router,
            })
    if config.with_mcp_server and config.has_web_app:
        # Phase 24: MCP surface alongside FastAPI. Requires the web/full
        # template because mcp_server.py imports app.dispatch / app.models.
        files.update({
            "app/mcp_server.py": mcp_files.render_mcp_server_module,
            "mcp_server_run.py": mcp_files.render_mcp_server_run,
        })
    if config.is_personalized:
        # Phase F: the per-client auto-optimization SaaS template. A base
        # fleet + built-in tools, a personalization module mirroring a
        # validated SaaS consumer (chat→ClientSpec → capability merge → datasource
        # auto-profile → compile_personalized → PersonalizationRun →
        # per-client .oac/promoted/<client_id>/ → serve), a FastAPI chat /
        # personalize / serve surface, a CLI, and mocked tests so the
        # generated project ships green per-client tests out of the box.
        # The base fleet replaces the single-agent starter registry with a
        # 2-3 role fleet exposing build_fleet_registry(...) + ROLES.
        files.update({
            "agents/__init__.py": personalized_files.render_fleet_package_init,
            "agents/registry.py": personalized_files.render_fleet_registry,
        })
        files.update({
            "personalization/__init__.py": personalized_files.render_package_init,
            "personalization/builtins.py": personalized_files.render_builtins,
            "personalization/elicit_runner.py": personalized_files.render_elicit_runner,
            "personalization/client_agent.py": personalized_files.render_client_agent,
            "personalization/orchestrate.py": personalized_files.render_orchestrate,
            "personalization/serving.py": personalized_files.render_serving,
            "app/personalize.py": personalized_files.render_api_router,
            "scripts/personalize_client.py": personalized_files.render_cli_script,
            "tests/__init__.py": lambda c: "",
            "tests/test_personalization.py": personalized_files.render_tests,
            "tests/test_adaptability.py": personalized_files.render_adaptability_tests,
            "config/settings.py": personalized_files.render_settings,
            "config/__init__.py": lambda c: "",
        })
    return files


class ScaffoldResult(BaseModel):
    model_config = ConfigDict(frozen=False)

    target: Path
    written_files: list[Path] = Field(default_factory=list)
    skipped_existing: list[Path] = Field(default_factory=list)
    preserved_user_files: list[Path] = Field(
        default_factory=list,
        description=(
            "Files the scaffold WOULD have rewritten but skipped because"
            " the user has modified them since the last scaffold run."
            " Re-run with --force-overwrite-all to nuke even these."
        ),
    )
    skill_files: list[Path] = Field(
        default_factory=list,
        description="Files written by the skill emitters (.opencode/skills, .claude/skills, CLAUDE.md).",
    )
    uv_sync_status: str = Field(
        default="not_attempted",
        description=(
            "Outcome of the post-scaffold `uv sync` step: not_attempted"
            " (flag off), uv_missing (binary not found), success, or"
            " failed:<exit_code>."
        ),
    )


class ScaffoldEngine(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: ScaffoldConfig

    def render(self) -> ScaffoldResult:
        from open_agent_compiler.scaffold.manifest import (
            classify_file, compute_hash, load_manifest, write_manifest,
        )
        target = self.config.target
        self._validate_target(target)
        target.mkdir(parents=True, exist_ok=True)
        result = ScaffoldResult(target=target)
        previous_manifest = load_manifest(target)
        new_hashes: dict[str, str] = {}
        for rel_path, generator in _file_map(self.config).items():
            full_path = target / rel_path
            content = generator(self.config)
            classification = classify_file(
                target, rel_path, content, previous_manifest,
            )
            if classification == "fresh":
                # Brand new file — always write.
                pass
            elif classification == "unchanged":
                # Already on disk + matches what we'd write. Record the
                # hash anyway so re-runs continue to track it.
                new_hashes[rel_path] = compute_hash(content)
                continue
            elif classification == "framework":
                # User hasn't touched this since last scaffold — safe
                # to refresh with current generator output (picks up
                # framework fixes).
                if not self.config.force_overwrite:
                    result.skipped_existing.append(full_path)
                    continue
            elif classification == "user":
                # User customised it. Preserve unless force_overwrite_all.
                if not self.config.force_overwrite_all:
                    result.preserved_user_files.append(full_path)
                    # Keep recording the user's current hash so future
                    # runs treat any further changes as user edits.
                    new_hashes[rel_path] = compute_hash(
                        full_path.read_text(),
                    )
                    continue
            elif classification == "orphan":
                # File exists with no manifest entry — assume user
                # intent. Same as 'user' classification.
                if not self.config.force_overwrite_all:
                    result.preserved_user_files.append(full_path)
                    new_hashes[rel_path] = compute_hash(
                        full_path.read_text(),
                    )
                    continue
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            new_hashes[rel_path] = compute_hash(content)
            result.written_files.append(full_path)
        write_manifest(target, new_hashes, previous=previous_manifest)
        self._emit_skills(result)
        if self.config.uv_sync:
            result.uv_sync_status = self._run_uv_sync(target)
        return result

    def _run_uv_sync(self, target: Path) -> str:
        """Run `uv sync` in the target dir so deps install automatically.

        Returns:
          - 'uv_missing'        — `uv` binary not on PATH; user runs sync
                                  themselves later. Non-fatal.
          - 'success'           — uv exited 0.
          - 'failed:<exit_code>' — uv exited non-zero (e.g. network
                                   issue, lockfile conflict).

        We deliberately do NOT raise on failure. The scaffold has
        already written every file; the user can re-run sync after
        fixing whatever uv complained about.
        """
        import shutil
        import subprocess
        if shutil.which("uv") is None:
            return "uv_missing"
        try:
            proc = subprocess.run(
                ["uv", "sync"], cwd=str(target),
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            return "failed:timeout"
        except Exception as exc:  # noqa: BLE001
            return f"failed:exception:{type(exc).__name__}"
        if proc.returncode == 0:
            return "success"
        return f"failed:{proc.returncode}"

    def _emit_skills(self, result: ScaffoldResult) -> None:
        if not self.config.skills:
            return
        bundles = list_skills()
        target = self.config.target
        if "opencode" in self.config.skills:
            out = emit_opencode(
                bundles, target, force=self.config.force_overwrite,
            )
            result.skill_files.extend(out.written)
        if "claude" in self.config.skills:
            out = emit_claude(
                bundles, target, force=self.config.force_overwrite,
            )
            result.skill_files.extend(out.written)

    def _validate_target(self, target: Path) -> None:
        from open_agent_compiler.scaffold.manifest import manifest_path
        if not target.exists() or not target.is_dir():
            return
        if self.config.force_overwrite:
            return
        # If a prior scaffold left a manifest, this is a known scaffold
        # project — safe to re-render in no-op mode (every file
        # classified 'unchanged' or 'user', skipped either way).
        if manifest_path(target).exists():
            return
        existing = [p for p in target.iterdir()]
        if existing:
            raise ValueError(
                f"target {target} is not empty and force_overwrite is False."
                f" Pass --force-overwrite to allow writing into it."
            )
