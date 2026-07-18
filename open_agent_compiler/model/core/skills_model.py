from __future__ import annotations

from pydantic import BaseModel
from open_agent_compiler.model.core.tools_model import ToolDefinition


class SkillExample(BaseModel):
    header: str | None
    condition: str | None
    result: str | None
    rule: str | None
    tools_used: list[ToolDefinition]


class WorkflowStep(BaseModel):
    header: str | None
    condition: str | None
    result: str | None
    rule: str | None
    tools_used: list[ToolDefinition]


class SkillDefinition(BaseModel):
    """
    Defines agent skill, can be compiled both as subagent or as skill
    """
    name: str
    description: str
    usage_explanation_long: str
    usage_explanation_short: str
    rules: list[str]
    workflow_steps: list[WorkflowStep]
    positive_examples: list[SkillExample]
    negative_examples: list[SkillExample]
