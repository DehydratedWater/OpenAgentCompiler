# 91 saas-personalized — the per-client auto-optimization SaaS template

`oac init --template saas-personalized` generates a repeatable, testable
per-client agentic-SaaS starter that is **pre-wired to the framework's
per-client auto-optimization** (the `PersonalizationRun` keystone, Phase E).

> **The moat.** A generic agent is a commodity. The defensible product is an
> agent **auto-tuned to each customer's private tools + data**. The platform
> ships a base flow + built-in tools; each client connects their own MCP tools
> and data sources; the framework auto-optimizes a *private per-client agent*
> that blends both surfaces and tunes its **tool use** (which tools, when, in
> what sequence) to the workflow the client described in chat — judged on real
> opencode tool-use trajectories, not final-text similarity.

## Run

```bash
uv run python examples/91_saas_personalized/scaffold.py
```

Produces (gitignored) under `examples/91_saas_personalized/generated/`:

| Folder | LLM | Extras |
|---|---|---|
| `zai/` | `zai-coding-plan` | per-client loop only |
| `postgres/` | `zai-coding-plan` | + run-tracking DB + MCP server surface |

The equivalent CLI invocation:

```bash
oac init ./my-saas \
  --template saas-personalized \
  --llm zai-coding-plan \
  --with-postgres --with-mcp-server
```

## What the template generates

```
generated/<name>/
  agents/
    registry.py            — base fleet (planner / worker / critic) +
                             build_fleet_registry(...) + ROLES + registry()
  personalization/
    builtins.py            — the platform's built-in tool surface
    elicit_runner.py       — the opencode teacher/judge client (GLM via opencode)
    client_agent.py        — build / compile / optimize / serve a per-client agent
    orchestrate.py         — personalize_client(...): the whole pipeline, injectable seams
    serving.py             — interactive (LangChain bind) + long-running (opencode session)
  app/
    main.py                — FastAPI app (includes the personalize router)
    personalize.py         — POST /personalize/{intake,optimize,serve}
  scripts/
    personalize_client.py  — CLI to run a REAL per-client optimization
  config/
    settings.py            — model refs (env-only) + per-client roots
  tests/
    test_personalization.py — fully MOCKED per-client tests (ship green)
  pyproject.toml, README.md, .env.example, docker/, .opencode/skills/, ...
```

## The per-client flow (chat → spec → merge → optimize → serve)

```
1. Elicit        POST /personalize/intake — chat → validated ClientSpec
                 (teacher = OpencodeMutatorClient, GLM via opencode)
2. Merge         built-in ∪ client MCP ∪ client datasources → one surface
                 (merged opencode.json + per-agent allow-list)
3. Auto-profile  each datasource enumerated/sampled → DatasourceProfile,
                 its derived tools folded into the merged surface
4. Compile       compile_personalized → a per-client opencode project root
                 (spec-derived prompt overlay + merged tools on every role)
5. Optimize      PersonalizationRun — GLM teacher (via opencode) rewrites
                 prompt+workflow+tool-use; local-qwen student runs FULL opencode
                 sessions; judge scores vs client criteria; winners promote to
                 .oac/promoted/<client_id>/
6. Serve         POST /personalize/serve — recompile applying promotions;
                 interactive via LangChain bind, long-running via opencode session
```

## Verifying the generated project (no live IO)

The generated per-client tests are fully mocked — fakes stand in for the
opencode runner, teacher, and judge, so there is **no live opencode / qwen /
z.ai** call:

```bash
cd examples/91_saas_personalized/generated/zai
PYTHONPATH=<repo-root>:. pytest tests/test_personalization.py -q   # 9 passed
```

## Running a real per-client optimization

From the host (the autoloop is opencode-only — never a raw provider API), with
the local qwen up and `opencode` authed for the zai-coding-plan provider:

```bash
PYTHONPATH=<repo-root>:. ZAI_API_KEY=... \
  python scripts/personalize_client.py \
    --client-id acme --chat chat.txt \
    --mcp-url https://mcp.example/acme/drive \
    --mcp-tools drive_search,drive_read --max-rounds 3 --target 0.7
```

Promotions land at `clients/clients/acme/.oac/promoted/acme/`. Re-run as the
client refines their requirements in chat.
