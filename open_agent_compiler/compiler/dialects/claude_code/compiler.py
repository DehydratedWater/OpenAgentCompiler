"""Claude Code compiler — writes to .claude/ instead of .opencode/.

Beyond the tree rename, this dialect emits `.claude/settings.json`:
Claude Code does NOT read the opencode-style `permission:` frontmatter
that rides along in the copied agent files — its real enforcement
surface is the settings permission rules. Without this file the
compiled permission model is advisory prose; with it, the bash
allowlists and read/write/edit toggles actually gate tool calls.

The mapping is project-level (settings.json has no per-agent scope):
- every tool's bash allowlist → `Bash(<pattern>:*)` allow rules,
- `Skill(<name>)` allows for every skill any agent declares,
- `Read`/`Write`/`Edit` allowed when ANY agent's tool_permissions
  allow them; denied only when at least one agent declared explicit
  permissions and NONE allow the capability (a uniform project stance).
"""

from __future__ import annotations

import json
import shutil
from typing import ClassVar

from open_agent_compiler.compiler.dialects.opencode.compile_permissions import (
    _bash_allow_patterns,
    _gather_tools,
)
from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler


def _claude_bash_rule(pattern: str) -> str:
    """opencode's `cmd *` prefix pattern → Claude's `Bash(cmd:*)` rule."""
    pattern = pattern.strip()
    if pattern.endswith(" *"):
        return f"Bash({pattern[:-2]}:*)"
    return f"Bash({pattern})"


class ClaudeCodeCompiler(OpenCodeCompiler):
    dialect_name: ClassVar[str] = "claude"

    def compile(self) -> None:
        # Compile to a temp subdir using the OpenCode shape, then move the
        # resulting .opencode/ tree to .claude/. Bundled scripts copy is
        # path-independent so it lands in the same `scripts/` directory.
        super().compile()
        src_dir = self.target / ".opencode"
        dst_dir = self.target / ".claude"
        if src_dir.exists():
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.move(str(src_dir), str(dst_dir))

        self._write_settings_json()

        # Native tool calling: Claude Code has no per-tool file format —
        # its native route is an MCP server. Emit the tools server and
        # register it in .mcp.json.
        if self.options.get("native_tools"):
            from open_agent_compiler.compiler.native_tools import (
                collect_json_tools,
                emit_claude_mcp_config,
                emit_mcp_tools_server,
            )
            if collect_json_tools(self.resolved_variants):
                emit_mcp_tools_server(self.target)
                emit_claude_mcp_config(self.target)

    def _write_settings_json(self) -> None:
        """Emit `.claude/settings.json` — Claude Code's real permission
        enforcement surface (see module docstring for the mapping)."""
        if not self.resolved_variants:
            return
        allow: list[str] = []
        deny: list[str] = []

        for agent in self.resolved_variants.values():
            for tool in _gather_tools(agent):
                if tool.bash_tool is None:
                    continue
                for pattern in _bash_allow_patterns(tool):
                    rule = _claude_bash_rule(pattern)
                    if rule not in allow:
                        allow.append(rule)
            for skill in agent.agent_definition.skills:
                rule = f"Skill({skill.name})"
                if rule not in allow:
                    allow.append(rule)

        explicit = [
            agent.agent_definition.tool_permissions
            for agent in self.resolved_variants.values()
            if agent.agent_definition.tool_permissions is not None
        ]
        for capability, rule in (("read", "Read"), ("write", "Write"),
                                 ("edit", "Edit")):
            if any(getattr(p, capability) for p in explicit):
                allow.append(rule)
            elif explicit:
                deny.append(rule)

        settings_dir = self.target / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(json.dumps(
            {"permissions": {"allow": allow, "deny": deny}}, indent=2,
        ) + "\n")
