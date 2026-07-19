# Testing agents

In this guide you'll embed tests directly on your agent and tool
definitions, run them with `oac test`, and read the JSONL results. The
framework's test model is mocks-first: every tool ships a mock, so the
whole suite runs green in CI with zero credentials.

If you haven't built an agent yet, start with
[your first agent](../getting-started/first-agent.md).

## 1. Know the three test kinds

All three are Pydantic models from `open_agent_compiler.model.core.test_model`,
embedded on the definitions they validate:

| Kind | Lives on | What it does |
|---|---|---|
| `CapabilityTest` | `AgentDefinition.capability_tests` | Pure introspection over the compiled artifact — permissions, tools, skills, bash patterns. No LLM, no I/O, milliseconds. |
| `ToolTest` | `ToolDefinition.tool_tests` (also agent- and skill-scoped) | Drives a tool's handler — or its mock — with an `input` dict and scores the output. |
| `AgentTest` | `AgentDefinition.agent_tests` | End-to-end scenario, single- or multi-turn. Needs an invoker callable at runtime because execution is deployment-specific. |

`oac test` runs capability and tool tests directly. AgentTests are
discovered too, but report as `not_runnable` until you wire an invoker
(an opencode subprocess, the [interactive runner](interactive-tier.md),
a simulator) — the framework can't guess how your agents execute.

## 2. Pick evaluators

Every test carries `evaluators` — a tuple of checks dispatched by their
`kind` discriminator. The registry in
`open_agent_compiler/testing/evaluation.py` ships eleven kinds:

| Kind | Class | Checks |
|---|---|---|
| `equals` | `EqualsEvaluator` | Whole-target or dotted-`field` equality |
| `substring` | `SubstringEvaluator` | `needle` present (case toggle) |
| `regex` | `RegexEvaluator` | `re.search` on `pattern` |
| `json_path` | `JsonPathEvaluator` | Dotted `path` (keys + indices) equals `expected` |
| `tool_called` | `ToolCalledEvaluator` | Recorded calls include `tool_name` (+ optional `with_args_subset`, `min_count`) |
| `tool_not_called` | `ToolNotCalledEvaluator` | No call with that name |
| `path_order` | `PathOrderEvaluator` | `steps` occur as an ordered subsequence of the trajectory (`contiguous=True` for strict pipelines) |
| `permission_present` | `PermissionPresentEvaluator` | Permission key / `bash_pattern` is allowed |
| `permission_absent` | `PermissionAbsentEvaluator` | Permission key is denied or missing |
| `llm_judge` | `LLMJudgeEvaluator` | Delegates `criteria` to a pluggable `JudgeClient`; `pass_threshold` gates |
| `fact_recall` | `FactRecallEvaluator` | Graded retrieval: fraction of `facts` recalled; any `forbidden` string zeroes the score (hallucination guard) |

An evaluator missing its context (e.g. `llm_judge` with no judge wired)
returns a clean *skipped* result, never a failure.

## 3. Write the tests — worked example

One agent, one mocked tool, all three test kinds (adapted from
`examples/70_oac_test` and `examples/32_multi_turn_mocks`):

```python
# agents.py
from open_agent_compiler import (
    AgentDefinition, AgentHeader, AgentRegistry, AgentTest,
    BashToolPermission, CapabilityTest, CompilationConfig, EqualsEvaluator,
    JsonPathEvaluator, MockProfile, MockResponse, ModelParameters,
    PermissionAbsentEvaluator, SubstringEvaluator, TemplateSlot,
    TemplateTree, ToolDefinition, ToolDefinitionHeader,
    ToolDefinitionLogicBash, ToolTest, Turn,
)

def echo_tool() -> ToolDefinition:
    return ToolDefinition(
        header=ToolDefinitionHeader(
            name="echo-tool", description="Echo text back.",
            usage_explanation_long="Echo the user's text.",
            usage_explanation_short="echo", rules=[],
        ),
        bash_tool=ToolDefinitionLogicBash(
            permission_bash=BashToolPermission(
                tool_name="bash", value="allow",
                allowed_commands=["uv run scripts/echo.py *"],
            ),
            positive_examples=["uv run scripts/echo.py --text hi"],
            negative_examples=[], mode_specific_rules=[],
        ),
        # The tool's default mock — what runs when no profile overrides it.
        mock=MockResponse(kind="fixed",
                          fixed_output={"text": "DEFAULT", "from": "tool.mock"}),
        tool_tests=[
            # Runs against the default mock (mock_profile=None).
            ToolTest(name="echo-default-mock", input={"text": "hi"},
                     evaluators=(EqualsEvaluator(field="from", expected="tool.mock"),)),
            # Runs against the 'ci' MockProfile registered below.
            ToolTest(name="echo-via-profile", input={"text": "hi"}, mock_profile="ci",
                     evaluators=(JsonPathEvaluator(path="from", expected="profile.ci"),)),
        ],
    )

def registry() -> AgentRegistry:
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="echo-agent", name="echo-agent",
                           description="Echoes user text."),
        usage_explanation_long="Always call echo-tool; return its text field.",
        usage_explanation_short="echo agent",
        system_prompt="Call echo-tool with the user's text; return its `text`.",
        extra_tools=[echo_tool()],
        capability_tests=[
            CapabilityTest(name="echo-bash-allowed",
                           must_have_bash_patterns=("uv run scripts/echo.py *",)),
            CapabilityTest(name="write-off-by-default",
                           evaluators=(PermissionAbsentEvaluator(permission_key="write"),)),
        ],
        agent_tests=[
            # Multi-turn: same session threads across turns; per-turn asserts.
            AgentTest(name="echo-conversation", mock_profile="ci",
                      turns=(Turn(prompt="say hi",
                                  expected_tool_calls=("echo-tool",),
                                  evaluators=(SubstringEvaluator(needle="CI-MOCK"),)),
                             Turn(prompt="again",
                                  expected_tool_calls=("echo-tool",)))),
        ],
    )
    agent_id = reg.register_agent("echo-agent", agent,
                                  ModelParameters(model_name="zai-coding-plan/glm-4.5-air",
                                                  temperature=0.0))
    reg.register_template(TemplateTree(name="tpl",
        slots=[TemplateSlot(name="primary", default_agent_id=agent_id)]))
    reg.create_compilation_config(CompilationConfig(name="prod", template_name="tpl"))
    reg.register_mock_profile(MockProfile(name="ci", responses={
        "echo-tool": MockResponse(kind="fixed",
                                  fixed_output={"text": "CI-MOCK", "from": "profile.ci"}),
    }))
    return reg
```

For stateful scenarios, `MockResponse` also supports `kind="sequence"`
(call N resolves through `sequence[N]`; out-of-bounds calls reuse the
last element) and `kind="stateful_callable"` (the callable receives a
`MockState` with a call counter and scratchpad) — see
`examples/32_multi_turn_mocks` for a monitoring agent driven by a
sequenced alert stream.

## 4. Run with `oac test`

```bash
uv run oac test agents:registry --config prod -v

# Subset by kind or name substring
uv run oac test agents:registry --config prod --kind tool
uv run oac test agents:registry --config prod --filter echo

# Bypass the green-hash cache
uv run oac test agents:registry --config prod --force
```

Expected first run for the example above:

```
oac test: discovered=5 passed=4 failed=0 skipped=0 not_runnable=1
```

Four pass (2 capability + 2 tool); the AgentTest is `not_runnable`
because no invoker is wired. Tests are auto-discovered from every agent
and every tool reachable through any agent in the resolved tree, deduped
by tool + test name. See the [CLI reference](../reference/cli.md) for
all flags (`--results`, `--variant`).

## 5. Read the JSONL artifacts

Each result appends one JSON object per line to
`.oac/test_results.jsonl` (override with `--results`):

```bash
tail -1 .oac/test_results.jsonl | python -m json.tool
```

Records carry the test name, pass/fail, per-evaluator evidence, and a
`composite_hash` — a SHA-256 over the agent state, model, mock-set
hash, access profile, and variant. On the next run, any test whose
composite hash matches a prior *passing* artifact is skipped
automatically, so editing agent B never re-runs agent A's green tests.
`--force` bypasses the cache.

## 6. Why mocks-first means CI needs no credentials

Every `ToolDefinition` can carry a default `MockResponse`, and
`MockProfile`s registered on the registry override per tool. Because
`oac test` resolves tools through mocks (real handlers only run when no
mock exists), the entire suite — permissions, tool contracts,
multi-turn agent scenarios — executes without a database, API key, or
LLM call. Point CI at `uv run oac test … --config prod` and it's
hermetic. The same artifacts then feed the
[improvement loop](improvement-loop.md) as its scoring evidence.
