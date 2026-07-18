"""Project scaffolding — `oac init` engine.

Configurable templater that generates a new project directory ready to
`docker compose up`. Templates and optional services are composed by
toggling flags on ScaffoldConfig; the engine writes the resolved files
to the target directory.

Configuration axes (mapped from `oac init` CLI flags):

- template: barebones | web | full
- llm: anthropic | openai | openrouter | vllm | zai-coding-plan
- with_postgres / with_redis / with_qdrant / with_ollama
- observability: none | langfuse
- proxy: none | nginx | traefik
- with_telegram_bot
- with_cron + cron_events_path

See [[reference-ecommerce-agent-scaffold]] for the proven base shape.
"""

from open_agent_compiler.scaffold.config import (
    LLMProvider,
    Observability,
    ProxyKind,
    ScaffoldConfig,
    Template,
)
from open_agent_compiler.scaffold.engine import ScaffoldEngine, ScaffoldResult

__all__ = [
    "LLMProvider",
    "Observability",
    "ProxyKind",
    "ScaffoldConfig",
    "Template",
    "ScaffoldEngine",
    "ScaffoldResult",
]
