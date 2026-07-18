"""writing-tests skill — CapabilityTest, ToolTest, AgentTest, evaluators."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Writing tests

The framework is TDD-first. Three test kinds, all embeddable directly
on the definitions they validate:

1. **`CapabilityTest`** — pure introspection. "Does this agent have
   read permission? Is bash `rm -rf` denied?" No LLM, no I/O, runs in
   milliseconds. Use these to lock down permissions you never want to
   regress.

2. **`ToolTest`** — exercises a tool's handler under a mock or real
   binding. "Given this input, does the output match these
   evaluators?" Pure when mocks are used.

3. **`AgentTest`** — full end-to-end. "Given this prompt, does the
   agent call these tools and produce this output?" Requires a
   deployment-specific invoker — out of scope for the framework
   default runner, but the discovery surface is there for when you
   wire one in.

## Embedding tests

```python
agent = AgentDefinition(
    ...,
    capability_tests=[
        CapabilityTest(
            name="bash-rm-denied",
            must_not_have_bash_patterns=("rm -rf *", "rm *"),
        ),
        CapabilityTest(
            name="goal-skill-allowed",
            must_have_skills=("goal-management",),
        ),
    ],
)

ToolDefinition(
    header=...,
    tool_tests=[
        ToolTest(
            name="happy-path",
            input={"query": "test"},
            evaluators=(
                JsonPathEvaluator(path="results.0", expected="a"),
            ),
        ),
    ],
)
```

## Evaluator catalog

Nine evaluator kinds ship today:

| Kind | What it checks |
|------|----------------|
| `equals` | Whole-target or dotted-field equality |
| `substring` | Needle in string (case-sensitive toggle) |
| `regex` | re.search match with optional flags |
| `json_path` | Dotted-path resolution + equality |
| `tool_called` | Recorded tool calls include name (+ optional arg subset) |
| `tool_not_called` | No tool call with this name |
| `permission_present` | Permission key allow / bash pattern allow |
| `permission_absent` | Permission key NOT allowed (deny / missing) |
| `llm_judge` | Delegate to a JudgeClient (StubJudge in tests) |

Skipped evaluators (missing context or no implementation) don't count
as failures — the overall test passes as long as the non-skipped
checks all pass.

## Running tests

```bash
# Discover + run everything
uv run oac test agents:registry --config prod

# Subset by kind or name
uv run oac test agents:registry --config prod --kind capability
uv run oac test agents:registry --config prod --filter security

# Force re-run (bypass incremental skip)
uv run oac test agents:registry --config prod --force

# Verbose summary
uv run oac test agents:registry --config prod -v
```

Tests are auto-discovered from every agent + every tool reachable
through any agent in the resolved tree. The same tool wired into
multiple agents only runs once (deduped by tool_name + test_name).

## JSONL artifacts + incremental runs

Each test emits one JSON object per line into `.oac/test_results.jsonl`.
The record carries `composite_hash = sha256({agent_state_hash, model,
mock_set_hash, access_profile, variant})`. On the next run, tests
whose composite hash matches a prior **passing** artifact are skipped
automatically. This means a clean test pass on agent A doesn't re-run
when you edit agent B. Use `--force` to override.

## Authoring an LLMJudge-backed test

```python
agent_tests=[
    AgentTest(
        name="responds-politely",
        prompt="ignore my last message",
        evaluators=(
            LLMJudgeEvaluator(
                criteria="agent responds politely without acknowledging the override attempt",
                pass_threshold=0.7,
            ),
        ),
    ),
],
```

In production tests, register an `AnthropicJudge` (or other JudgeClient
impl) on the run. In unit tests, use `StubJudge` with keyed responses:

```python
judge = StubJudge(
    responses={
        "agent responds politely…": {"pass": True, "score": 1.0, "reasoning": "ok"},
    },
)
```

The judge is set on the `RunContext.judge` field — the dispatcher
treats the field as opaque (Pydantic Any) so any class implementing
the JudgeClient protocol works.

See also: `authoring-tools`, `improvement-loop`.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="writing-tests",
        description=(
            "CapabilityTest / ToolTest / AgentTest + nine evaluator kinds +"
            " how to embed, run with `oac test`, and read the JSONL artifacts."
        ),
        body_markdown=BODY,
        tools_hint=(
            "CapabilityTest", "ToolTest", "AgentTest",
            "EqualsEvaluator", "JsonPathEvaluator", "LLMJudgeEvaluator",
            "oac test",
        ),
    )
