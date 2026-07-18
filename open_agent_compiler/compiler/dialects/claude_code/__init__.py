"""Claude Code dialect — same shape as OpenCode but emits .claude/ tree.

Claude Code reads agents from .claude/agents/ and a project-level
CLAUDE.md. The artifact shapes are otherwise compatible with the
OpenCode dialect — the workflow prompt + permissions + custom_tools
blocks all transfer; only the on-disk location differs.

For Phase 8.2 this dialect subclasses OpenCodeCompiler and overrides
the output paths; future work can diverge the frontmatter / runtime
conventions as Claude Code's spec evolves.
"""
