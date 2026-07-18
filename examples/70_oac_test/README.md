# 70 oac test — embedded tests + JSONL artifacts

`oac test` discovers `CapabilityTest`s on `AgentDefinition` and
`ToolTest`s on `ToolDefinition`, runs them, and emits one JSONL line
per result so downstream tooling can incrementally skip passing tests.

## What this example carries

- **4 CapabilityTests** on the echo-agent — pure introspection over
  the compiled permission dict:
  - `echo-bash-allowed` — `uv run scripts/echo.py *` is in the allowlist
  - `echo-skill-allowed` — the skill is allowed
  - `dangerous-bash-denied` — `rm -rf *` is NOT in the allowlist
  - `write-permission-off-by-default` — `permission.write` is absent
- **2 ToolTests** on the echo-tool:
  - `echo-default-mock` — uses `ToolDefinition.mock` (no profile)
  - `echo-via-mock-profile` — uses the `ci` MockProfile registered on
    the registry, which overrides the tool's default mock
- **A registered `MockProfile`** named `ci` so the second tool test
  has a profile to bind against.

## Run

```bash
uv run oac test "examples.70_oac_test.agents:registry" --config prod -v
```

Expect output like:
```
  pass 'echo-bash-allowed'
  pass 'echo-skill-allowed'
  pass 'dangerous-bash-denied'
  pass 'write-permission-off-by-default'
  pass 'echo-default-mock'
  pass 'echo-via-mock-profile'

oac test: discovered=6 passed=6 failed=0 skipped=0 not_runnable=0
```

## Run again — incremental skip

```bash
uv run oac test "examples.70_oac_test.agents:registry" --config prod -v
```

This time:
```
  skip 'echo-bash-allowed': matches green run from 2026-…
  skip 'echo-skill-allowed': matches green run from …
  …
oac test: discovered=6 passed=0 failed=0 skipped=6 not_runnable=0
```

Composite hashes are stored in `.oac/test_results.jsonl` (next to the
example dir) and matched on subsequent runs. Pass `--force` to bypass.

## Inspect the JSONL artifacts

```bash
head -1 .oac/test_results.jsonl | python -m json.tool
```

Each record carries: `test_kind / test_name / target_name / passed /
score / duration_s / variant / access_profile / mock_profile / model /
agent_state_hash / mock_set_hash / composite_hash / evidence /
skip_reason`. The composite hash is what enables incremental skip.

## What's exercised

- `CapabilityTest` with must_have / must_not_have shorthand AND
  explicit evaluators.
- `ToolTest.mock_profile` resolving to a registered MockProfile (vs
  falling back to `ToolDefinition.mock`).
- 9-kind evaluator dispatcher — equals / json_path /
  permission_present / permission_absent / substring / regex / etc.
- `register_mock_profile` on the registry.
- JSONL artifact emitter + GreenIndex skip.
- `oac test --verbose / --force / --filter / --kind` CLI flags.
