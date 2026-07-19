# Skills

In this guide you'll learn both things the framework calls a "skill": **agent
skills** (`SkillDefinition`s compiled into an agent's prompt so the *compiled
agent* gains a capability) and **developer skill bundles** (`SkillBundle`s
that `oac sync-skills` installs into a consumer project so *coding agents
working in that repo* know the framework). You'll write a skill factory,
attach it to an agent, inspect the compiled output, and deploy the bundled
developer docs.

## 1. Write an agent skill

A `SkillDefinition` bundles 1-4 related tools with cross-tool rules and a
mini-workflow. Group by *intent* ("I want time awareness"), not by file
location — the agent's `skills=[]` list becomes its capability inventory:

```python
from open_agent_compiler import SkillDefinition, WorkflowStep

def time_skill() -> SkillDefinition:
    return SkillDefinition(
        name="time-awareness",
        description="Pulls the current time from a deterministic script.",
        usage_explanation_long=(
            "Wrap the time-tool. When the user asks anything time-related,"
            " call the tool and incorporate its `iso` field into the answer."
        ),
        usage_explanation_short="time queries",
        rules=[
            "Always cite the timezone returned by the tool.",
            "Never invent a time; always call the tool.",
        ],
        workflow_steps=[
            WorkflowStep(header="Resolve the requested timezone",
                         condition=None,
                         result="timezone_hours integer ready",
                         rule="Default to 0 (UTC) if the user didn't specify.",
                         tools_used=[]),
            WorkflowStep(header="Call the time tool",
                         condition=None,
                         result="ISO timestamp returned",
                         rule="Pass timezone_hours and read the iso field.",
                         tools_used=[time_tool()]),
        ],
        positive_examples=[], negative_examples=[],
    )
```

The tools a skill references (via `tools_used`) travel with it — you don't
wire them into the agent separately.

## 2. Attach skills to an agent

```python
agent = AgentDefinition(
    header=AgentHeader(agent_id="time-assistant", name="time-assistant",
                       description="Knows the time."),
    usage_explanation_long="Answers time questions using the time-tool.",
    usage_explanation_short="time helper",
    system_prompt="Answer time questions by calling the time-tool.",
    skills=[time_skill()],
)
```

`examples/30_tools/` is the runnable version of this exact setup.

## 3. Inspect what a compiled skill looks like

After `CompileScript(...).run()`, the agent's `.opencode/agents/<slot>.md`
carries the skill in two places:

- **Frontmatter** — a default-deny skill allowlist plus the skill's tool
  permissions:

  ```yaml
  permission:
    skill:
      '*': deny
      time-awareness: allow
    bash:
      '*': deny
      uv run scripts/time_tool.py *: allow
  ```

- **Prompt body** — a `## Your Skills` section rendering each skill's
  description, numbered workflow (header, rule, result per step), rules, and
  the tools it uses. The SECURITY POLICY block lists allowed skills too, so
  enforcement and awareness stay in sync.

## 4. Share skills as factories

Because a `SkillDefinition` is just a Pydantic value returned by a function,
the sharing pattern is a plain factory module: one `def <name>_skill() ->
SkillDefinition` per capability, imported by every agent that needs it. A
production fleet of ~105 agents shares 72 such skill factories — each agent
composes its inventory from the shared pool rather than re-declaring tools.
Keep factories pure (no I/O at import time) so registries stay cheap to build
and easy to test.

## 5. Deploy the developer skill bundles: `oac sync-skills`

Separately, the package ships **14 developer skill bundles** — opinionated
markdown docs (`getting-started`, `project-orchestration`,
`authoring-agents`, `authoring-tools`, `tool-variants`, `prompt-structure`,
`writing-tests`, `providers-and-models`, `variants-and-profiles`,
`docker-and-compose`, `improvement-loop`, `sandboxed-scripting`,
`dynamic-extractor`, `interactive-agents`) that teach coding agents the
framework itself. Install or refresh them in any consumer project:

```bash
uv run oac sync-skills . --skills opencode,claude   # deploy / refresh both
uv run oac sync-skills . --check                    # drift report, exit 1 on drift
uv run oac sync-skills . --force                    # rewrite even if fresh
```

What gets written:

- `<project>/.opencode/skills/<name>/SKILL.md` + a `.skill_version` sidecar
- `<project>/.claude/skills/<name>/SKILL.md` + sidecar, plus an aggregated
  `CLAUDE.md` index pointing at every skill
- `<project>/.pi/skills/<name>/SKILL.md` + sidecar (`--skills pi`)
- `<project>/.codex/skills/<name>/SKILL.md` + sidecar (`--skills codex`)

All four use the same cross-agent `SKILL.md` standard — one directory
per skill, YAML frontmatter with `name` and `description` — so a bundle
authored once deploys to every harness.

The sidecar stores the bundle's content hash, making sync idempotent:
`--check` reports each skill as fresh / stale / missing without writing, and
a plain run skips up-to-date skills. `oac init --skills opencode,claude`
deploys them at scaffold time, so a freshly-scaffolded project's coding agent
already knows how to author agents, tools, and tests.

Programmatic access mirrors the CLI: `open_agent_compiler.skills` exposes
`list_skills()`, `get_skill(name)`, `emit_opencode(...)`, `emit_claude(...)`,
`emit_pi(...)`, `emit_codex(...)`, and `check_drift(...)` if you want to
embed the sync in your own tooling.

## Related pages

- [Agent model concepts](../concepts/agent-model.md)
- [Authoring tools](tools.md) — the tools your skills bundle
- [Workflows and subagents](workflows-and-subagents.md)
- [Testing](testing.md)
- [CLI reference](../reference/cli.md) — full `oac sync-skills` flags
