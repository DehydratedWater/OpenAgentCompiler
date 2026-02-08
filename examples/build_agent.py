"""Build a code-reviewer agent and write OpenCode project files to build/."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler._types import (
    AgentPermissions,
    ModelConfig,
    ModelOptions,
    ProviderConfig,
    ProviderOptions,
)
from open_agent_compiler.builders import (
    AgentBuilder,
    ConfigBuilder,
    SkillBuilder,
    ToolBuilder,
)
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.writers import OpenCodeWriter

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def main() -> None:
    # -- Tools (from handler scripts) --
    db_query = ToolBuilder().from_script(str(SCRIPTS_DIR / "db_query.py")).build()
    file_search = ToolBuilder().from_script(str(SCRIPTS_DIR / "file_search.py")).build()

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

    # -- Config (rich provider/model hierarchy) --
    config = (
        ConfigBuilder()
        .provider(
            ProviderConfig(
                name="anthropic",
                options=ProviderOptions(api_key="env:ANTHROPIC_API_KEY"),
                models=(
                    ModelConfig(
                        name="sonnet",
                        id="claude-sonnet-4-5-20250929",
                        options=ModelOptions(temperature=0.0),
                    ),
                ),
            )
        )
        .default_model("anthropic/sonnet")
        .compaction(auto=True, prune=True)
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
        .skill(
            data_skill,
            instruction="Use when you need to query databases or search files",
        )
        .system_prompt(
            "You are a thorough code reviewer. Examine code for correctness, "
            "security, performance, and style. Be specific in your feedback."
        )
        .mode("primary")
        .temperature(0.0)
        .color("#4A90D9")
        .steps(100)
        .permissions(AgentPermissions(doom_loop="deny"))
        .build()
    )

    # -- Compile & write --
    compiled = compile_agent(agent_def, target="opencode")

    writer = OpenCodeWriter(
        output_dir=BUILD_DIR,
        scripts_dir=SCRIPTS_DIR,
    )
    writer.write(compiled)
    print(f"Build output written to {BUILD_DIR}")


if __name__ == "__main__":
    main()
