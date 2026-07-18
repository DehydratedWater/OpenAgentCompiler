# 32 multi-turn-mocks — sequenced mocks for monitoring scenarios

Demonstrates Phase 11's multi-turn `AgentTest` + sequenced
`MockResponse`. A monitoring agent that polls an alert stream
across three turns:

| Turn | Mock returns | Expected response |
|---|---|---|
| 1: "check now" | `{alerts: []}` | "No new alerts" |
| 2: "check again" | `{alerts: [ALERT-001]}` | "ALERT-001 …" |
| 3: "anything now?" | `{alerts: []}` | "No new alerts" |

The sequenced mock lets the test exercise the *temporal* behaviour
(first quiet, then an alert, then quiet again) without needing a
real alert stream. Past the sequence length, the final element is
reused — so a long session naturally terminates in the steady-state
case.

## Inspect the test definition

```bash
uv run python examples/32_multi_turn_mocks/agents.py
```

Prints the AgentTest's turns + the mock sequence so you can see
the shape end-to-end:

```
AgentTest: 'monitor-three-checks' (multi_turn=True)
  turns: 3
  turn 1: prompt='check now'
    expected_tool_calls: ('fetch-alerts',)
    evaluator: SubstringEvaluator(needle='No new alerts')
  turn 2: prompt='check again'
    ...

Mock profile 'stream-mocks':
  fetch-alerts.kind = sequence
  sequence length   = 3
    call 0: {'alerts': []}
    call 1: {'alerts': [{'id': 'ALERT-001', ...}]}
    call 2: {'alerts': []}
```

## Variants

- **stateful_callable** mock kind: the mock fn receives a MockState
  with a scratchpad dict so it can compute the response from prior
  calls (e.g., return alerts only after the user has asked twice).
  Use when sequenced fixed responses aren't expressive enough.
- **Top-level `prompt`** on AgentTest stays the back-compat path
  for single-turn tests. The runner threads session state across
  turns when `turns` is set; capability subsets of the test still
  work without an invoker.

See the `writing-tests` skill for evaluator details.
