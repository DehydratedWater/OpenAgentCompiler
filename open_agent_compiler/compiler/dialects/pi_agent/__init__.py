"""Pi Agent dialect — compile agents for the pi runtime.

Pi agents are defined as markdown files with YAML frontmatter in the
`.pi/agents/` directory. This dialect generates those files from the
open-agent-compiler agent model.

The pi runtime (with @tintinweb/pi-subagents extension) provides:
- Subagent spawning via the `Agent()` tool
- Background/foreground agent execution
- Live widget UI showing agent status
- Skill preloading
- Persistent agent memory
- Git worktree isolation

See: https://pi.dev/packages/@tintinweb/pi-subagents
"""
