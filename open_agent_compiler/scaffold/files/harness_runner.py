"""Generator for app/harness.py — the dialect-agnostic worker invoker.

The FastAPI dispatcher's async opencode runner is opencode-optimized
(JSON event stream, XDG session wiring). Everything else that needs to
run a compiled agent — the telegram bot, the batch runners, ad-hoc
scripts — goes through this thin adapter instead, which resolves the
right `HarnessRunner` for the project's compile dialect (opencode, pi,
codex, claude, or a registered custom one).
"""

from __future__ import annotations

from open_agent_compiler.scaffold.config import ScaffoldConfig


def render_harness_module(config: ScaffoldConfig) -> str:
    return (
        '"""Dialect-agnostic invoker for the compiled workers in build/.\n'
        "\n"
        "Uses the framework's harness-runner registry, so the same call works\n"
        f'whether this project compiles for "{config.dialect}" or you later\n'
        "switch dialects — change HARNESS (or the OAC_HARNESS env var) and\n"
        "recompile.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "from open_agent_compiler.improvement import get_runner\n"
        "\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
        'BUILD_DIR = PROJECT_ROOT / "build"\n'
        f'HARNESS = os.environ.get("OAC_HARNESS", "{config.dialect}")\n'
        "\n"
        "\n"
        "def run_compiled_agent(\n"
        "    agent_name: str, prompt: str, *, timeout_s: float = 300.0,\n"
        ") -> str:\n"
        '    """Run one compiled agent to completion and return its text.\n'
        "\n"
        "    Raises RuntimeError on harness failure — an empty answer with a\n"
        "    surfaced error is a harness problem, not a model answer.\n"
        '    """\n'
        "    runner = get_runner(HARNESS, BUILD_DIR)\n"
        "    result = runner.run(\n"
        "        agent_name=agent_name, prompt=prompt, timeout_s=timeout_s,\n"
        "    )\n"
        "    if result.error:\n"
        "        raise RuntimeError(result.error)\n"
        "    return result.final_text()\n"
    )
