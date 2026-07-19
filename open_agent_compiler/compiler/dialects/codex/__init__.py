"""Codex dialect — compile agents for the OpenAI Codex CLI runtime.

Codex custom agents are standalone TOML files in the `.codex/agents/`
directory (project scope) or `~/.codex/agents/` (personal scope). Each
file defines one agent: `name`, `description`, and
`developer_instructions` are required; optional keys reuse the standard
Codex config surface (`model`, `model_reasoning_effort`, `sandbox_mode`,
`mcp_servers`, …).

This dialect generates `.codex/agents/<name>.toml` files from the
open-agent-compiler agent model. Unlike pi/opencode there is no
per-agent tool allowlist — Codex constrains agents through
`sandbox_mode` (derived here from `tool_permissions`) and spawns
subagents from natural-language delegation in the instructions rather
than an explicit spawn tool.

See:
- https://developers.openai.com/codex/subagents
- https://developers.openai.com/codex/config-reference
"""
