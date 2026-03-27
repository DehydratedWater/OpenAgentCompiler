# OpenAgentCompiler

Python-first agent framework that compiles agent definitions into backend-specific configurations for [OpenCode](https://github.com/opencode-ai/opencode) agents.

## Installation

```bash
pip install open-agent-compiler
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add open-agent-compiler
```

For local/editable development:

```bash
uv add --editable ../OpenAgentCompiler
```

## Quick start

```python
from open_agent_compiler.builders import AgentBuilder, ConfigBuilder, ToolBuilder
from open_agent_compiler.compiler import compile_agent
from open_agent_compiler.writers import OpenCodeWriter
from open_agent_compiler._types import (
    ModelConfig, ModelOptions, ProviderConfig, ProviderOptions,
)

# Define a tool
search = (
    ToolBuilder()
    .name("file-search")
    .description("Search files by glob pattern")
    .from_script("scripts/file_search.py")
    .build()
)

# Configure the model
config = (
    ConfigBuilder()
    .provider(ProviderConfig(
        name="anthropic",
        options=ProviderOptions(api_key="env:ANTHROPIC_API_KEY"),
        models=(ModelConfig(
            name="sonnet",
            id="claude-sonnet-4-5-20250929",
            options=ModelOptions(temperature=0.0),
        ),),
    ))
    .default_model("anthropic/sonnet")
    .build()
)

# Build the agent
agent = (
    AgentBuilder()
    .name("my-agent")
    .description("My custom agent")
    .config(config)
    .tool(search)
    .system_prompt("You are a helpful assistant.")
    .build()
)

# Compile and write to disk
compiled = compile_agent(agent, target="opencode")
OpenCodeWriter(output_dir="build/").write(compiled)
```

## Architecture

```
Builder -> AgentDefinition -> Compiler -> backend dict -> Writer -> disk -> Manager -> external process
```

- **Builders** -- Fluent API classes that produce immutable data types via `.build()`
- **Compiler** -- Transforms an `AgentDefinition` into a backend-specific dict
- **Writers** -- Persist compiled dicts to disk (project files, configs, scripts)
- **Managers** -- Async lifecycle managers that deploy/invoke/teardown agents

## Development

```bash
uv sync --all-extras      # install with dev + bench deps
uv run pytest tests/ -v   # run all tests
uv run ruff check .       # lint
uv run mypy               # type check
```

## Python version

Requires Python 3.12+.

## License

See [LICENSE](LICENSE) for details.
