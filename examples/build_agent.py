"""Build a code-reviewer agent and write OpenCode project files to build/."""

from __future__ import annotations

import json
from pathlib import Path

from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    ToolBuilder,
)
from open_agent_compiler.compiler import compile_agent

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"


def _write_opencode_json(compiled: dict[str, object]) -> None:
    """Write the top-level opencode.json config."""
    model = compiled["model"]
    tools = compiled["tools"]
    config = {
        "provider": model["provider"],  # type: ignore[index]
        "model": model["id"],  # type: ignore[index]
        "theme": "dark",
        "tools": {t["name"]: {"allow": True} for t in tools},  # type: ignore[union-attr]
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


def main() -> None:
    # -- Tools --
    read_file = (
        ToolBuilder()
        .name("read_file")
        .description("Read file contents from disk")
        .parameter("path", {"type": "string"})
        .build()
    )
    grep = (
        ToolBuilder()
        .name("grep")
        .description("Search file contents with regex")
        .parameter("pattern", {"type": "string"})
        .parameter("path", {"type": "string"})
        .build()
    )
    bash = (
        ToolBuilder()
        .name("bash")
        .description("Execute a shell command")
        .parameter("command", {"type": "string"})
        .build()
    )

    # -- Skills --
    security_review = (
        SkillBuilder()
        .name("security-review")
        .description("Review code for security vulnerabilities")
        .instructions(
            "Scan the code for OWASP top-10 vulnerabilities.\n"
            "Pay special attention to injection flaws, broken auth, and XSS.\n"
            "Report findings with severity and remediation steps."
        )
        .tool(read_file)
        .tool(grep)
        .build()
    )
    test_review = (
        SkillBuilder()
        .name("test-review")
        .description("Verify test coverage and quality")
        .instructions(
            "Check that tests exist for all public functions.\n"
            "Verify edge cases and error paths are covered.\n"
            "Run the test suite and report failures."
        )
        .tool(read_file)
        .tool(bash)
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
        .tool(read_file)
        .tool(grep)
        .tool(bash)
        .skill(security_review)
        .skill(test_review)
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
    print("Done.")


if __name__ == "__main__":
    main()
