"""Bundled infrastructure scripts shipped with open-agent-compiler.

These scripts are copied into a compiled tree's `scripts/` directory by
the OpenCodeCompiler when the agent's workflow references them
(subagent_todo via todo_mode; workspace_io via workspace; opencode_manager
via subagents in 'primary' mode).

Importing this package does NOT execute the scripts — they run as
standalone CLIs from inside the compiled tree. The Python module form
is provided so the compiler can locate them at copy time.
"""
