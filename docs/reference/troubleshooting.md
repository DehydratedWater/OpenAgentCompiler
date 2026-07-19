# Troubleshooting

Symptoms first, causes second. Each entry names the failure as you'll actually
see it, then the fix.

## Install & imports

### `oac compile: No module named 'agents'`

The factory spec (`agents:registry`) is imported with the **current working
directory** on the path. Run `oac` from the project root that contains
`agents/` (or `agents.py`), or install your project into the environment.

### `opencode: command not found`

The compiler writes files; running them needs the opencode CLI on your `PATH`.
Install it per [installation](../getting-started/installation.md), then verify
with `opencode --version`. In scaffolded projects the Docker images bundle
opencode, so this only bites host-side runs.

### `uv sync` fails in a scaffolded project

The generated `pyproject.toml` must resolve `open-agent-compiler`. If you are
working against a source checkout of the framework rather than the published
package, the project needs a `[tool.uv.sources]` entry pointing at that
checkout — regenerate with a current `oac init`, or add the entry manually.

## Provider auth

### Runs fail with 401 / "provider not configured"

`oac compile` never contacts an LLM, so auth problems only surface at run time.
Check, in order:

1. opencode knows the provider: `opencode auth login`, or the provider block in
   your opencode config (`opencode.json`). The `model:` line in the compiled
   agent frontmatter (`provider/model-id`) must match a configured provider.
2. Scaffolded projects read keys from `.env` (copied from `.env.example`) — the
   compose services load it via `env_file`; an empty key there means every
   container run fails auth while host runs may still work, or vice versa.
3. Reproduce outside your own stack: `cd build && opencode run --agent primary
   "hi"`. If that fails, it is configuration, not your code.

## Runtime failures

### `opencode run` hangs at startup

Known file-sink deadlock in some opencode versions. Launch with
`opencode run --print-logs ...` — the extra sink avoids the hang. Scaffolded
runners already do this.

### `database is locked` under concurrent runs

Concurrent opencode processes sharing one `XDG_DATA_HOME` contend on the same
SQLite database. Give each concurrent run a private, throwaway data dir:

```bash
XDG_DATA_HOME=$(mktemp -d) opencode run --agent primary "..."
```

Auth lives in config, not in `XDG_DATA_HOME`, so throwaway dirs are safe.

### Empty output from the model — especially "thinking" models

Empty assistant text is **almost never the model**. Diagnose in this order:

1. **Agent not found.** opencode reports `Agent not found: "..."` as an error
   event *while still exiting 0*; naive parsers read that as empty text. Run
   the agent from a stable project dir (one carrying an `opencode.json`) and
   keep agent files **flat-named** — `.opencode/agents/name.md`, never
   `.opencode/agents/group/name.md`. Surface opencode `{"type":"error"}`
   events in any harness you build.
2. **Token starvation on hybrid reasoning models** (e.g. Qwen3.x): the model
   can spend the whole budget thinking and return no visible content. Raise the
   output budget. Do not reflexively disable thinking — with reliable agent
   discovery and an adequate budget, thinking-on is stable. Full post-mortem:
   [thinking models and opencode scoring](../lessons/thinking-models-and-opencode-scoring.md).
3. **Local OpenAI-compatible endpoints** calling Qwen3.x directly (the
   interactive tier): pass `enable_thinking=false` or request structured
   output, otherwise `content` comes back empty.

### Compiled agent flails on a custom tool

If the agent calls your ScriptTool with invented `--command` verbs or falls
back to `ls` and `--help`, the prompt does not name the exact verbs. Put every
supported command verb verbatim in the tool's usage docs so the compiler can
surface them — see the [tools guide](../guides/tools.md).

### Pi build ignores MCP servers

Expected: the pi dialect does not map `mcp_servers` and emits a compile
warning. Configure `ext:mcp/<tool>` on the pi side manually.

## Testing & improvement

### `oac test` is green but the live agent misbehaves

Embedded tests run against **mocks** by design: `ToolTest`s use
`ToolDefinition.mock` or a registered `MockProfile`, and capability tests
introspect the compiled artifacts — none of them call a live LLM. Green means
"the contract and compilation are right", not "the model behaves". Validate
behavior with a live `opencode run` or an improvement-loop evaluation. See
[testing](../guides/testing.md) for the mock-vs-live boundary.

### `oac test` reports `skipped=N` on a rerun

The green-hash cache: tests whose composite hash (agent state + mock set)
matches a previous passing run are skipped. Pass `--force` to rerun
everything. `not_runnable` counts tests that lacked what they need to execute
(e.g. a named mock profile that isn't registered) — fix the wiring rather than
forcing.

### Improvement scores flat at 0.00

A scoreboard where everything is exactly `0.000` is an infrastructure signal,
not a quality signal. Check:

1. The compiled config loads at all — `opencode run` one agent manually. A
   rejected config (one malformed field is enough) zeroes every probe.
2. Agent discovery (see "Empty output" above) — not-found errors scored as
   empty text are the classic mass-zero cause.
3. Infra timeouts on contended local endpoints should be **skipped**, not
   scored 0, or they flood the floor of the scoreboard.

### `oac promote` exits with code 2

A promotion for that component already exists in `.oac/promoted/`. Pass
`--force` to replace it, or `--class <label>` to promote into a separate
per-model-class slot. Use `--show` first to inspect what you're promoting.
