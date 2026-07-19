"""Codex compiler — writes `.codex/agents/<name>.toml` files.

Codex custom agents are standalone TOML files: `name`, `description`,
and `developer_instructions` are required; `model` and `sandbox_mode`
reuse the standard Codex config keys. Codex spawns subagents from
natural-language delegation in the prompt — there is no explicit spawn
tool — so orchestrator instructions phrase delegation directly.

This compiler maps the open-agent-compiler agent model onto that format:

- `agent_definition.header.description` → `description`
- `model_parameters.model_name` → `model`
- `agent_definition.system_prompt` or workflow body → `developer_instructions`
- `agent_definition.tool_permissions` → `sandbox_mode`
  (read-only unless write/edit is allowed)
- `agent_definition.mcp_servers` → `[mcp_servers.<name>]` tables
  (url-based servers only; stdio servers warn)
- `agent_definition.subagents` → referenced in the instructions body

An `AGENTS.md` index is written at the target root so Codex sessions
started in the build tree know which custom agents exist and when to
delegate to them.

See: https://developers.openai.com/codex/subagents
"""

from __future__ import annotations

import warnings
from typing import ClassVar

from open_agent_compiler.compiler.build_graph import topological_order
from open_agent_compiler.compiler.core.compiler import Compiler
from open_agent_compiler.compiler.dialects.codex.compile_agent import compile_codex_agent_toml
from open_agent_compiler.compiler.dialects.opencode.compile_scripts import compile_scripts


class CodexCompiler(Compiler):
    dialect_name: ClassVar[str] = "codex"
    supports_features: ClassVar[frozenset[str]] = frozenset({
        "workflow",
        "subagents",
        "skills",
        "permissions",
        "todo_modes",
        "split_profiles",
        "mcp_servers",
    })

    def compile(self) -> None:
        """Compile all agent variants into `.codex/agents/` TOML files."""
        self.target.mkdir(parents=True, exist_ok=True)

        # Always create the .codex/agents/ directory even if no agents
        agents_dir = self.target / ".codex" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Per-tool scripts: the instructions document extra_tools as
        # shell-invocable, so the backing script files must exist in the
        # codex tree too. variants=None skips opencode's bundled
        # infrastructure scripts — the codex prompts never reference them.
        all_tools = []
        for agent in self.resolved_variants.values():
            agent_tools = list(agent.agent_definition.extra_tools)
            for skill in agent.agent_definition.skills:
                for wf_step in skill.workflow_steps:
                    agent_tools.extend(wf_step.tools_used)
            all_tools.extend(agent_tools)
        compile_scripts(self.target, all_tools, variants=None)

        # Stdio MCP servers (no url) can't be emitted completely — a
        # `command` entry is required, which the OAC model doesn't carry.
        # Dropping them silently would strip agent capability without a
        # trace, so warn loudly instead. Per-server tool allowlists have
        # no codex mapping either.
        for slot_name, agent in self.resolved_variants.items():
            for server in agent.agent_definition.mcp_servers:
                if not server.url:
                    warnings.warn(
                        f"codex dialect: agent {slot_name!r} declares stdio"
                        f" MCP server {server.name!r} (no url) — add a"
                        " `command` entry to the [mcp_servers."
                        f"{server.name}] table manually.",
                        stacklevel=2,
                    )
                if server.allowed_tools:
                    warnings.warn(
                        f"codex dialect: agent {slot_name!r} restricts MCP"
                        f" server {server.name!r} to tools"
                        f" {server.allowed_tools} — codex has no per-server"
                        " tool allowlist; the restriction is not enforced.",
                        stacklevel=2,
                    )

        # Parents (orchestrators) first — order is informational but
        # consistent with the other dialects.
        order = topological_order(self.resolved_variants)
        for slot_name in order:
            agent = self.resolved_variants[slot_name]
            compile_codex_agent_toml(
                self.target, slot_name, agent.postfix, agent,
            )
            # Dual-compile: codex agents are all directly spawnable, but
            # the `-primary` twin keeps name parity with the other
            # dialects so cross-dialect tooling can address either file.
            if (
                agent.also_compile_as_primary
                and agent.agent_mode != "primary"
            ):
                primary_variant = agent.model_copy(
                    update={"agent_mode": "primary"},
                )
                compile_codex_agent_toml(
                    self.target, slot_name,
                    f"{agent.postfix}-primary",
                    primary_variant,
                )

        self._write_agents_md(order)

    def _write_agents_md(self, order: list[str]) -> None:
        """Write an AGENTS.md index so Codex sessions in the build tree
        know which custom agents exist and when to delegate."""
        if not order:
            return
        lines: list[str] = [
            "# Custom Agents",
            "",
            "This project ships compiled custom agents in `.codex/agents/`.",
            "Delegate to them by spawning the named agent as a subagent:",
            "",
        ]
        for slot_name in order:
            agent = self.resolved_variants[slot_name]
            defn = agent.agent_definition
            desc = defn.header.description or defn.usage_explanation_short
            lines.append(f"- **{slot_name}{agent.postfix}** — {desc}")
        lines.append("")
        (self.target / "AGENTS.md").write_text("\n".join(lines))
