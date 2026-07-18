"""Workflow-prompt rendering for the OpenCode dialect.

Decomposed into small concern-per-module builders so each piece of v1's
1300-line procedural generator is independently understandable and
testable. The top-level WorkflowPromptBuilder composes them.

Module map:
    builder.py          - WorkflowPromptBuilder (composition)
    step_block.py       - per-step renderer (gate, tools, eval, instructions,
                          subagents, marks_done, routes)
    final_checklist.py  - "ASK YOURSELF" block at the end
    (later phases add: skills_section, todo_block, subagent_section,
     security_policy, postfix_rewrite)
"""

from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.builder import (
    WorkflowPromptBuilder,
)
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt.compose import compose_body

__all__ = ["WorkflowPromptBuilder", "compose_body"]
