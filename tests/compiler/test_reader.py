"""Reading a compiled agent artifact back into its parts."""

from __future__ import annotations

from open_agent_compiler.compiler.reader import (
    CompiledAgent,
    load_compiled_agent,
    parse_compiled_agent,
)

COMPILED = """\
---
description: A terse critic.
model: zai-coding-plan/glm-4.6
mode: primary
---
You are a terse ad critic.

Score the copy and return JSON.

---
(an inline horizontal rule that must survive parsing)
"""


def test_parse_extracts_model_and_prompt():
    a = parse_compiled_agent(COMPILED, name="critic-primary")
    assert isinstance(a, CompiledAgent)
    assert a.name == "critic-primary"
    assert a.model == "zai-coding-plan/glm-4.6"
    assert a.system_prompt.startswith("You are a terse ad critic.")
    assert a.frontmatter["mode"] == "primary"
    # the inline '---' in the body survived
    assert "horizontal rule that must survive" in a.system_prompt


def test_parse_no_frontmatter():
    a = parse_compiled_agent("just a system prompt, no frontmatter")
    assert a.model is None
    assert a.system_prompt == "just a system prompt, no frontmatter"
    assert a.frontmatter == {}


def test_load_from_disk(tmp_path):
    p = tmp_path / "strategist-primary.md"
    p.write_text(COMPILED, encoding="utf-8")
    a = load_compiled_agent(p)
    assert a.name == "strategist-primary"
    assert a.model == "zai-coding-plan/glm-4.6"
