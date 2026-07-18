"""`pyproject.toml` generator."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.scaffold.config import ScaffoldConfig


def _framework_source_root() -> Path | None:
    """Locate the framework checkout the running `oac` was loaded from.

    When the running framework is a source checkout (its pyproject.toml
    sits next to the `open_agent_compiler` package), scaffolds get a
    `[tool.uv.sources]` path entry pointing back at it so they track the
    local checkout instead of the PyPI release. Returns None when the
    framework was installed from a registry (scaffolds then depend on
    the published `open-agent-compiler` wheel).
    """
    import open_agent_compiler

    root = Path(open_agent_compiler.__file__).resolve().parent.parent
    if (root / "pyproject.toml").exists():
        return root
    return None


_LLM_DEPS = {
    "anthropic": ['"anthropic>=0.39.0"'],
    "openai": ['"openai>=1.50.0"'],
    "openrouter": ['"openai>=1.50.0"'],  # uses openai SDK against openrouter base
    "vllm": ['"openai>=1.50.0"'],  # vLLM speaks OpenAI-compat
    "zai-coding-plan": [],  # uses opencode runtime via subprocess
}


def render(config: ScaffoldConfig) -> str:
    deps: list[str] = [
        '"open-agent-compiler>=1.0.0",',
        '"python-dotenv>=1.0.0",',
        '"loguru>=0.7.3",',
    ]
    deps += [f"{d}," for d in _LLM_DEPS.get(config.llm, [])]
    if config.has_web_app:
        deps += [
            '"fastapi>=0.115.0",',
            '"uvicorn[standard]>=0.32.0",',
            '"pydantic>=2.0",',
        ]
    if config.is_personalized:
        # The interactive serve path binds the tuned agent via LangChain
        # (`personalization.serving.bind_interactive_agent`); optional but
        # pinned so the generated project's interactive path works out of box.
        deps += [
            '"langchain-core>=0.3.0",',
            '"langchain-openai>=0.2.0",',
        ]
    if config.with_postgres or config.template == "full":
        deps += [
            '"sqlalchemy[asyncio]>=2.0",',
            '"asyncpg>=0.30.0",',
            '"alembic>=1.13.0",',
        ]
    if config.with_redis:
        deps += ['"redis>=5.0.0",']
    if config.with_mcp_server:
        deps += ['"mcp>=1.0.0",']
    if config.with_qdrant:
        deps += ['"qdrant-client>=1.10.0",']
    if config.with_telegram_bot or config.template == "full":
        deps += ['"python-telegram-bot>=21.0",']
    if config.observability == "langfuse":
        deps += ['"langfuse>=2.50.0",']

    dep_block = "\n    ".join(deps)
    source_root = _framework_source_root()
    uv_sources = ""
    if source_root is not None:
        uv_sources = (
            "\n"
            "# Resolve open-agent-compiler from the framework checkout that\n"
            "# scaffolded this project instead of PyPI. Remove this block to\n"
            "# track the published release instead.\n"
            "[tool.uv.sources]\n"
            f'open-agent-compiler = {{ path = "{source_root}", editable = true }}\n'
        )
    return (
        "[project]\n"
        f'name = "{config.project_name}"\n'
        'version = "0.1.0"\n'
        f'description = "Scaffolded by oac init (template={config.template})."\n'
        'readme = "README.md"\n'
        'requires-python = ">=3.12"\n'
        "dependencies = [\n"
        f"    {dep_block}\n"
        "]\n"
        f"{uv_sources}"
        "\n"
        "[dependency-groups]\n"
        "dev = [\n"
        '    "pytest>=8.3.0",\n'
        '    "pytest-asyncio>=0.24.0",\n'
        "]\n"
        "\n"
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["."]\n'
        'testpaths = ["tests"]\n'
        'asyncio_mode = "auto"\n'
    )
