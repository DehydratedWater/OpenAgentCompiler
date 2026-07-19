"""Pi Agent dialect — compile agents for the pi runtime.

Pi agents are defined as markdown files with YAML frontmatter in the
`.pi/agents/` directory. This dialect generates those files from the
open-agent-compiler agent model.

Compiled agents expect the pi runtime to run with TWO extensions:

1. `@tintinweb/pi-subagents` — subagent spawning. Provides:
   - Subagent spawning via the `Agent()` tool
   - Background/foreground agent execution
   - Live widget UI showing agent status
   - Skill preloading
   - Persistent agent memory
   - Git worktree isolation
2. `pi-permission-system` — permission enforcement. The frontmatter
   `tools:` allowlist and `disallowed_tools:` this dialect emits are
   only *enforced* at tool-call time by this extension (deterministic
   allow/deny/ask gates for tools, bash, MCP, and skills, plus ask
   forwarding from non-UI subagents). Without it the SECURITY POLICY
   block in the prompt body is advisory only.

See:
- https://pi.dev/packages/@tintinweb/pi-subagents
- https://github.com/MasuRii/pi-permission-system
"""
