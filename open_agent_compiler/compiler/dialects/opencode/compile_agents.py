import yaml
from pathlib import Path

from open_agent_compiler.compiler.dialects.opencode.tool_schema import tool_json_block
from open_agent_compiler.compiler.dialects.opencode.workflow_prompt import compose_body
from open_agent_compiler.model.core.agent_model import AgentVariant


def _gather_tools_for_schema(agent: AgentVariant):
    seen = {}
    for tool in agent.agent_definition.extra_tools:
        seen.setdefault(tool.header.name, tool)
    for skill in agent.agent_definition.skills:
        for wf in skill.workflow_steps:
            for tool in wf.tools_used:
                seen.setdefault(tool.header.name, tool)
    return list(seen.values())


def _custom_tool_blocks(agent: AgentVariant) -> list[dict]:
    """One OpenCode-style tool block per tool that opts into json/both."""
    blocks: list[dict] = []
    for tool in _gather_tools_for_schema(agent):
        fmt = agent.agent_definition.chosen_format(tool)
        if fmt not in ("json", "both"):
            continue
        block = tool_json_block(tool)
        if block is not None:
            blocks.append(block)
    return blocks


def compile_agent_markdown(target: Path, slot_name: str, postfix: str, agent: AgentVariant, permissions_dict: dict) -> str:
    frontmatter = {
        "description": agent.agent_definition.header.description or agent.agent_definition.header.name,
        "model": agent.model_parameters.model_name,
        "mode": agent.agent_mode,
        **permissions_dict,
    }
    custom_tools = _custom_tool_blocks(agent)
    if custom_tools:
        frontmatter["custom_tools"] = custom_tools
    
    # We dump yaml
    frontmatter_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    
    lines = []
    lines.append("---")
    lines.append(frontmatter_yaml.strip())
    lines.append("---")
    lines.append("")
    
    lines.append(f"# {agent.agent_definition.header.name}")
    lines.append("")
    if agent.agent_definition.header.description:
        lines.append(agent.agent_definition.header.description)
        lines.append("")

    body = compose_body(agent)
    if body:
        lines.append(body)
        lines.append("")
    
    if agent.agent_definition.skills:
        lines.append("## Your Skills")
        lines.append("")
        for skill in agent.agent_definition.skills:
            lines.append(f"### {skill.name}")
            lines.append("")
            lines.append(skill.usage_explanation_long)
            lines.append("")
            
            if skill.workflow_steps:
                lines.append("#### Workflow")
                lines.append("")
                for i, step in enumerate(skill.workflow_steps, 1):
                    lines.append(f"{i}. **{step.header}** — {step.rule}")
                    if step.condition:
                        lines.append(f"   Condition: {step.condition}")
                    if step.result:
                        lines.append(f"   Result: {step.result}")
                lines.append("")
                
            if skill.positive_examples:
                lines.append("#### Examples")
                for ex in skill.positive_examples:
                    if ex.header:
                        lines.append(f"**{ex.header}**")
                    if ex.rule:
                        lines.append(ex.rule)
                    lines.append("")

    content = "\n".join(lines)

    # OpenCode reads agents from <project>/.opencode/agents/<name>.md
    # (with subdirectories when the slot/name carries a /, e.g.
    # persona/quick.md). The slot+postfix is the file stem so
    # `opencode run --agent <slot><postfix>` resolves correctly. Slot
    # naming preserves the registry's templating model.
    agent_name = f"{slot_name}{postfix}"
    agents_dir = target / ".opencode" / "agents"
    file_path = agents_dir / f"{agent_name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return content
