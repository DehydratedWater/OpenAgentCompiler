"""Pi Agent compiler — writes `.pi/agents/<name>.md` files.

Pi agents are defined as markdown files with YAML frontmatter in the
`.pi/agents/` directory. The frontmatter declares the agent's tools,
model, thinking level, skills, and other configuration. The body is the
system prompt.

This compiler maps the open-agent-compiler agent model onto the pi agent
format:

- `agent_definition.header.description` → frontmatter `description`
- `model_parameters.model_name` → frontmatter `model`
- `agent_definition.system_prompt` or workflow body → markdown body
- `agent_definition.extra_tools` → frontmatter `tools` (bash tool names)
- `agent_definition.skills` → frontmatter `skills` (comma-separated)
- `agent_definition.subagents` → referenced in prompt body
- Permissions → `tools` allowlist and `disallowed_tools`

Pi agents are always "primary" in the sense that they're defined as
standalone `.md` files. Subagent spawning happens at runtime via the
`Agent()` tool, so we don't need the dual-compile (primary/subagent)
pattern from OpenCode for subagent invocation. However, we still honor
`also_compile_as_primary` to emit a `-primary.md` twin for direct
invocation (e.g. via pi's CLI or from other primaries).

See: https://pi.dev/packages/@tintinweb/pi-subagents
"""

from __future__ import annotations

import warnings
from typing import ClassVar

from open_agent_compiler.compiler.build_graph import topological_order
from open_agent_compiler.compiler.core.compiler import Compiler
from open_agent_compiler.compiler.dialects.opencode.compile_scripts import compile_scripts
from open_agent_compiler.compiler.dialects.pi_agent.compile_agent import compile_pi_agent_markdown


class PiAgentCompiler(Compiler):
    dialect_name: ClassVar[str] = "pi"
    supports_features: ClassVar[frozenset[str]] = frozenset({
        "workflow",
        "subagents",
        "skills",
        "permissions",
        "todo_modes",
        "split_profiles",
    })

    def compile(self) -> None:
        """Compile all agent variants into `.pi/agents/` markdown files."""
        self.target.mkdir(parents=True, exist_ok=True)

        # Always create the .pi/agents/ directory even if no agents
        agents_dir = self.target / ".pi" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Per-tool scripts: the agent body documents extra_tools as
        # "invoke via bash", so the backing script files must exist in
        # the pi tree too. variants=None skips opencode's bundled
        # infrastructure scripts (subagent_todo / workspace_io /
        # opencode_manager) — the pi prompts never reference them.
        all_tools = []
        for agent in self.resolved_variants.values():
            agent_tools = list(agent.agent_definition.extra_tools)
            for skill in agent.agent_definition.skills:
                for wf_step in skill.workflow_steps:
                    agent_tools.extend(wf_step.tools_used)
            all_tools.extend(agent_tools)
        compile_scripts(self.target, all_tools, variants=None)

        # MCP servers have no pi mapping yet (pi uses extension tools,
        # `ext:mcp/<tool>`); dropping them silently would strip agent
        # capability without a trace, so warn loudly instead.
        for slot_name, agent in self.resolved_variants.items():
            if agent.agent_definition.mcp_servers:
                names = ", ".join(
                    s.name for s in agent.agent_definition.mcp_servers
                )
                warnings.warn(
                    f"pi dialect: agent {slot_name!r} declares MCP"
                    f" server(s) [{names}] which the pi compiler cannot"
                    " map yet — configure them manually as pi extension"
                    " tools (ext:mcp/<tool>).",
                    stacklevel=2,
                )

        # Parents (orchestrators) first so later phases can implement
        # stub-overwrite semantics safely; for now order is informational
        # but consistent.
        order = topological_order(self.resolved_variants)
        for slot_name in order:
            agent = self.resolved_variants[slot_name]
            compile_pi_agent_markdown(
                self.target, slot_name, agent.postfix, agent,
            )
            # Dual-compile: when the slot opted in, ALSO emit a primary-
            # mode .md so the same agent is reachable via pi's CLI or
            # from other primaries. Skip when the slot is already primary
            # — the original file would collide with itself.
            if (
                agent.also_compile_as_primary
                and agent.agent_mode != "primary"
            ):
                primary_variant = agent.model_copy(
                    update={"agent_mode": "primary"},
                )
                compile_pi_agent_markdown(
                    self.target, slot_name,
                    f"{agent.postfix}-primary",
                    primary_variant,
                )
