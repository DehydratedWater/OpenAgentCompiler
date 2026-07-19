"""Compile the SAME tree into the full 2×2 worker matrix + both models.

    build_opencode/.opencode/agents/{primary,summarizer,critic}.md        (fast model)
    build_opencode/.opencode/agents/{primary,...}-smart.md                (smart model)
    build_pi/.pi/agents/{primary,summarizer,critic}.md                    (fast model)
    build_pi/.pi/agents/{primary,...}-smart.md                            (smart model)

Each dialect's compile passes `target=<dialect>+<class>` into the
registry factory, so per-target autoloop winners (improve_matrix.py +
`oac promote --target`) land in the right build. Every compile is
recorded in the run store (.oac/improvement.db) for traceability.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

from agents import registry  # noqa: E402
from open_agent_compiler import ModelPreset, SamplingDefaults  # noqa: E402
from open_agent_compiler.compiler.script import CompileScript  # noqa: E402
from open_agent_compiler.model.core.variant_spec import VariantSpec  # noqa: E402

STORE_URL = f"sqlite:///{HERE / '.oac' / 'improvement.db'}"

FAST = ModelPreset(
    name="fast", provider="zai-coding-plan", model_id="glm-4.5-air",
    sampling=SamplingDefaults(temperature=0.4),
)
SMART = ModelPreset(
    name="smart", provider="zai-coding-plan", model_id="glm-5.1",
    sampling=SamplingDefaults(temperature=0.2),
)

VARIANTS = [
    VariantSpec(name="fast", postfix="", preset=FAST),
    VariantSpec(name="smart", postfix="-smart", preset=SMART),
]


def main() -> None:
    for dialect in ("opencode", "pi"):
        # The promoted winner for THIS harness (fast class drives the
        # default files; -smart files share the harness-level prompt).
        target_key = f"{dialect}+fast"
        result = CompileScript(
            target=HERE / f"build_{dialect}",
            factory=lambda: registry(target=target_key),  # noqa: B023
            config="prod",
            dialect=dialect,
            variants=VARIANTS,
            clean=True,
            store_url=STORE_URL,
        ).run()
        print(f"[{dialect}] wrote {len(result.written_files)} file(s)"
              f" (target slot: {target_key})")
    print("\n✓ 2 harnesses × 2 models compiled from one definition.")
    print("  Improve per target next:  uv run python"
          " examples/85_matrix_live_chat/improve_matrix.py")


if __name__ == "__main__":
    main()
