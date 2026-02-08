"""Build a code-reviewer agent and write OpenCode project files to build/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    ToolBuilder,
)
from open_agent_compiler.compiler import compile_agent

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def _write_opencode_json(compiled: dict[str, object]) -> None:
    """Write the top-level opencode.json config."""
    model = compiled["model"]
    tools = compiled["tools"]
    config = {
        "provider": model["provider"],  # type: ignore[index]
        "model": model["id"],  # type: ignore[index]
        "theme": "dark",
        "tool": tools,  # bash permission dict
    }
    path = BUILD_DIR / "opencode.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  {path}")


def _write_agent_md(compiled: dict[str, object]) -> None:
    """Write .opencode/agents/<name>.md with YAML frontmatter."""
    agent = compiled["agent"]
    name: str = agent["name"]  # type: ignore[index]
    description: str = agent["description"]  # type: ignore[index]
    system_prompt: str = agent["system_prompt"]  # type: ignore[index]

    agents_dir = BUILD_DIR / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        system_prompt,
        "",
    ]
    path = agents_dir / f"{name}.md"
    path.write_text("\n".join(lines))
    print(f"  {path}")


def _write_skill_mds(compiled: dict[str, object]) -> None:
    """Write .opencode/skills/<skill>/SKILL.md with YAML frontmatter."""
    for skill in compiled["skills"]:  # type: ignore[union-attr]
        skill_name: str = skill["name"]  # type: ignore[index]
        skill_dir = BUILD_DIR / ".opencode" / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        tool_names: list[str] = skill["tools"]  # type: ignore[index]
        tools_yaml = ", ".join(tool_names) if tool_names else ""

        lines = [
            "---",
            f"name: {skill_name}",
            f"description: {skill['description']}",
            f"tools: [{tools_yaml}]",
            "---",
            "",
            skill["instructions"],  # type: ignore[list-item]
            "",
        ]
        path = skill_dir / "SKILL.md"
        path.write_text("\n".join(lines))
        print(f"  {path}")


def _copy_scripts(compiled: dict[str, object]) -> None:
    """Copy handler scripts to build/scripts/."""
    scripts_out = BUILD_DIR / "scripts"
    scripts_out.mkdir(parents=True, exist_ok=True)
    for script_file in compiled["scripts"]:  # type: ignore[union-attr]
        src = SCRIPTS_DIR / script_file  # type: ignore[arg-type]
        dst = scripts_out / script_file  # type: ignore[arg-type]
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  {dst}")
        else:
            print(f"  WARNING: {src} not found, skipping")


def main() -> None:
    # -- Tools (from handler scripts) --
    db_query = (
        ToolBuilder()
        .from_script(str(SCRIPTS_DIR / "db_query.py"))
        .file_path("db_query.py")  # override to relative for build output
        .build()
    )
    file_search = (
        ToolBuilder()
        .from_script(str(SCRIPTS_DIR / "file_search.py"))
        .file_path("file_search.py")
        .build()
    )

    # -- Skills --
    data_skill = (
        SkillBuilder()
        .name("data-query")
        .description("Query databases and search files")
        .instructions(
            "Use the available tools to query databases and search files.\n"
            "Always validate SQL before execution."
        )
        .tool(db_query)
        .tool(file_search)
        .build()
    )

    # -- Config --
    config = (
        ConfigBuilder()
        .model("claude-sonnet-4-5-20250929")
        .provider("anthropic")
        .temperature(0.0)
        .max_tokens(8192)
        .build()
    )

    # -- Agent --
    agent_def = (
        AgentBuilder()
        .name("code-reviewer")
        .description("Automated code review agent")
        .config(config)
        .tool(db_query)
        .tool(file_search)
        .skill(data_skill)
        .system_prompt(
            "You are a thorough code reviewer. Examine code for correctness, "
            "security, performance, and style. Be specific in your feedback."
        )
        .build()
    )

    # -- Compile --
    compiled = compile_agent(agent_def, target="opencode")

    # -- Write build output --
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    print("Writing build output:")
    _write_opencode_json(compiled)
    _write_agent_md(compiled)
    _write_skill_mds(compiled)
    _copy_scripts(compiled)
    print("Done.")


if __name__ == "__main__":
    main()
