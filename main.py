"""Convenience launcher equivalent to `oac`.

Lets `uv run main.py …` work the same as the installed `oac` console
script. Everything real lives under open_agent_compiler.cli.
"""

from open_agent_compiler.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
