"""autoloop-interview skill — collect goals + metrics from the user."""

from __future__ import annotations

from open_agent_compiler.skills.bundle import SkillBundle

BODY = """\
# Autoloop interview — turn user intent into measurable goals

Before an autoloop can improve an agent, the project needs a measurable
definition of "better". This skill is a WORKFLOW for you (the coding
agent): interview the user, write their answers into
`improve/goals.yaml`, verify the plan, and hand back the run command.
Trigger phrases: "interview me for the autoloop goals", "set up
optimization", "how do we measure this agent".

## The interview (ask in this order, one block at a time)

1. **Outcome** — "In one sentence: when this agent handles a request
   perfectly, what happened?" Push past vague answers ("be helpful") to
   observable outcomes ("the user got a runnable SQL query and a
   one-line explanation").
2. **Audience & inputs** — "Who sends the requests, and what do 3-5
   REAL inputs look like?" Collect them verbatim — these become probe
   prompts. Ask for at least one tricky/adversarial input.
3. **Quality bar** — For each input: "What must a good answer contain?
   What would make you reject an answer?" Map the answers:
   - objectively checkable → `substring` probes (a string a correct
     answer must contain),
   - judgment calls → `llm_judge` probes (write the user's own words
     into `criteria` — plain language, what GOOD looks like).
4. **Hard constraints** — "Anything the agent must NEVER do?" These
   become extra probes with adversarial prompts, or `contract_gate`
   predicates when delivery happens through a tool call.
5. **Where it runs** — "Which harnesses/models must this perform on?"
   Map to targets: the project's compile dialect, `interactive` if
   there's a realtime tier (telegram bot / chat), plus
   `<harness>+<class>` per model class in use.
6. **Tolerance** — "What failure rate is acceptable?" → sets
   `pass_rate_floor` (default 0.8). And "How much tuning per run?" →
   `rounds` (default 2).

## Write the answers

Fill `improve/goals.yaml` (the scaffold ships the skeleton):

```yaml
component: primary
goal: >-
  <the one-sentence outcome, user's words>
targets:
  - opencode
  - interactive
probes:
  - id: <slug of input 1>
    prompt: "<the user's real input, verbatim>"
    judge:
      kind: llm_judge
      criteria: "<what a good answer looks like, user's words>"
  - id: <slug of the adversarial input>
    prompt: "<tricky input>"
    judge:
      kind: substring
      needle: "<string a correct answer must contain>"
pass_rate_floor: 0.8
rounds: 2
```

## Verify, then run

```bash
uv run python improve/run_improve.py --dry-run   # show the plan back to the user
uv run python improve/run_improve.py             # run the loops
uv run oac versions list <component>             # what won, per target
```

Read the winners' prompts back to the user and confirm the judged
behavior matches their intent — a judge criteria that mis-states the
goal optimizes the wrong thing (see the optimize-the-real-goal lesson).
Baseline scores from the FIRST run are the benchmark; keep goals.yaml
under version control so the definition of better evolves deliberately.

## When the loop needs more than prompts

- Delivery through a tool call → gate with `contract_gate` predicates
  so undelivered candidates score 0 regardless of prose quality.
- Multiple models → add `<harness>+<class>` targets; promotion slots
  keep winners separate (see the optimization-targets skill).
- Stochastic outputs → duplicate probes (same prompt, several ids) so
  one lucky sample can't win a round.
"""


def build() -> SkillBundle:
    return SkillBundle(
        name="autoloop-interview",
        description=(
            "Interview the user to turn intent into measurable autoloop"
            " goals: outcome, real inputs, judge criteria, constraints,"
            " targets, tolerance — written into improve/goals.yaml and"
            " verified with a dry run."
        ),
        body_markdown=BODY,
        version="1.0.0",
    )
