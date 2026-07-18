"""File generators for the scaffolding engine.

Each module exports a render(config: ScaffoldConfig) -> str function
that returns the full file contents for one path. The engine maps
{path → generator} per template.
"""
