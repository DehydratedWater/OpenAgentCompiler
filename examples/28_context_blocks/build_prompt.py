"""Compose an agent's system_prompt from volatility-tagged blocks.

Demonstrates Phase 19's ContextBlock + PromptAssembler. Run with:

    uv run python examples/28_context_blocks/build_prompt.py

The script prints:
1. The composed prompt with blocks auto-sorted by volatility
2. The cacheable prefix (everything up to the first volatile block)
3. The cacheable prefix when the user changes — same prefix re-used
4. The full prompt rendered with a different live observation —
   only the volatile tail changes, prefix is identical (cache hit)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_agent_compiler import ContextBlock, PromptAssembler  # noqa: E402


# 1. immutable — never changes session-to-session
persona = ContextBlock(
    name="persona", volatility="immutable",
    description="Core identity statement.",
    content=(
        "You are a thorough research assistant. You explain trade-offs"
        " explicitly and never invent citations."
    ),
)
security = ContextBlock(
    name="security-rules", volatility="immutable",
    content=(
        "SECURITY POLICY:\n"
        "- Never run sudo.\n"
        "- Never write outside the project workspace.\n"
        "- Never call external APIs without explicit user consent."
    ),
)

# 2. stable — changes rarely (deploys, content edits)
skills_toc = ContextBlock(
    name="skills-toc", volatility="stable",
    content=(
        "Available skills (call via bash):\n"
        "- web-search: search the web for a query\n"
        "- summarise: condense a long document\n"
        "- citation-check: verify a reference exists"
    ),
)

# 3. fluid — changes per session
user_profile = ContextBlock(
    name="user-profile", volatility="fluid",
    content=lambda ctx: (
        f"USER:\n"
        f"  name: {ctx['name']}\n"
        f"  timezone: {ctx['tz']}\n"
        f"  preferences: {ctx.get('prefs', 'none')}"
    ),
)

# 4. volatile — changes per turn
recent_obs = ContextBlock(
    name="live-observations", volatility="volatile",
    content=lambda ctx: f"LIVE: {ctx['observations']}",
)


def main() -> None:
    assembler = PromptAssembler(blocks=[
        # Declared in arbitrary order — assembler will sort.
        recent_obs, user_profile, persona, skills_toc, security,
    ])

    session_alice = {
        "name": "Alice", "tz": "UTC+1", "prefs": "concise",
        "observations": "User asked at 14:02: 'find papers on X'",
    }
    session_bob = {
        "name": "Bob", "tz": "UTC-5",
        "observations": "User asked at 09:15: 'summarise yesterday'",
    }

    print("=== Composed prompt (Alice, turn 1) ===\n")
    print(assembler.compose(session_alice))

    print("\n=== Cacheable prefix (everything up to volatile) ===\n")
    print(assembler.cacheable_prefix(session_alice))

    print("\n=== Same prefix with Alice's next turn (different observations) ===")
    session_alice_t2 = {**session_alice, "observations": "User asked at 14:03: 'narrow to 2024'"}
    prefix_t2 = assembler.cacheable_prefix(session_alice_t2)
    same = (assembler.cacheable_prefix(session_alice) == prefix_t2)
    print(f"\nprefix identical across turns? {same}  ← cache-friendly")

    print("\n=== Different user (Bob) — fluid block changes, immutable+stable still cache ===")
    bob_prefix = assembler.cacheable_prefix(session_bob)
    immut_stable = "\n\n".join([
        persona.render(), security.render(), skills_toc.render(),
    ])
    overlap = bob_prefix.startswith(immut_stable)
    print(f"Bob's prefix starts with same immutable+stable section? {overlap}")
    print("(fluid block within prefix differs per user — that's expected)")


if __name__ == "__main__":
    main()
