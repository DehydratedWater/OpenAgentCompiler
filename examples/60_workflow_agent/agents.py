"""A workflow agent with gates, criteria, routes, marks_done + strict todos.

Demonstrates the full Phase 3 WorkflowStepDefinition surface in one
agent:

- 4 steps with explicit ids + names + instructions
- A Gate on step 2 (only execute if step-1's evaluation produced a
  specific value)
- A Criterion on step 1 (with `possible_values` enumerated)
- Routes from step 2 that jump to step 4 conditionally
- marks_done on each step so the strict-mode workflow renders the
  per-step `subagent_todo.py update` lines
- todo_mode = "strict" so STEP 0 (task list), per-step marks, and the
  final verification block all render
- workspace set so STEP 0a (workspace_io init) also renders
- preamble + postamble wrapping the workflow

The compiled prompt is a complete MANDATORY WORKFLOW with every
optional piece of the workflow grammar visible.
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    Criterion,
    Gate,
    GateCheck,
    ModelParameters,
    Route,
    TemplateSlot,
    TemplateTree,
    ToolUse,
    WorkflowStepDefinition,
)


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    triage = AgentDefinition(
        header=AgentHeader(
            agent_id="ticket-triage",
            name="ticket-triage",
            description="Triage support tickets through a strict workflow.",
        ),
        usage_explanation_long=(
            "Reads a support ticket and routes it through 4 explicit"
            " steps: classify, decide-route, draft-response, finalise."
            " Strict todo mode + workspace sandbox so every step is"
            " auditable."
        ),
        usage_explanation_short="strict ticket triage workflow",
        preamble=(
            "# Support Ticket Triage\n"
            "\n"
            "You handle incoming tickets via a strict procedure. Every"
            " ticket goes through the same 4 steps — never skip ahead."
        ),
        postamble=(
            "Remember: every output you produce must be auditable. If"
            " in doubt, mark the task in-progress and ask the user."
        ),
        todo_mode="strict",
        workspace=".agent_workspace/{name}",
        workflow=[
            WorkflowStepDefinition(
                id=1,
                name="ClassifySeverity",
                todo_name="classify",
                todo_description="Pick severity ∈ {low, medium, high}.",
                instructions=(
                    "Read the user's ticket. Decide its severity. Record"
                    " the result in your todo list as `severity = <value>`."
                ),
                evaluates=(
                    Criterion(
                        name="severity",
                        question="How severe is the ticket?",
                        possible_values=("low", "medium", "high"),
                    ),
                ),
                marks_done=("classify",),
            ),
            WorkflowStepDefinition(
                id=2,
                name="EscalateIfHigh",
                todo_name="escalate",
                todo_description="Only runs when severity=high.",
                gate=Gate(checks=(GateCheck(variable="severity", value="high"),)),
                instructions=(
                    "When the gate matched, write a one-paragraph"
                    " escalation note to ops. Otherwise skip this step."
                ),
                routes=(
                    Route(criteria_name="severity", value="low", goto_step=4),
                    Route(criteria_name="severity", value="medium", goto_step=3),
                ),
                marks_done=("escalate",),
            ),
            WorkflowStepDefinition(
                id=3,
                name="DraftResponse",
                todo_name="draft",
                todo_description="Write the user-facing reply.",
                instructions=(
                    "Write a 3-sentence reply to the user. First sentence:"
                    " acknowledge; second: action; third: ETA."
                ),
                tool_uses=(
                    ToolUse(
                        tool_name="rule-checker",
                        note="(future: verify the reply matches policy)",
                    ),
                ),
                marks_done=("draft",),
            ),
            WorkflowStepDefinition(
                id=4,
                name="Finalise",
                todo_name="finalise",
                todo_description="Compose the audit trail.",
                instructions=(
                    "Compose the final response: classification + (if"
                    " applicable) escalation note + draft reply, joined"
                    " under labelled headings."
                ),
                marks_done=("finalise",),
            ),
        ],
    )

    agent_id = reg.register_agent(
        "ticket-triage", triage,
        ModelParameters(model_name="zai-coding-plan/glm-5.1", temperature=0.2),
    )
    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg


if __name__ == "__main__":
    r = registry()
    print(f"agents: {r.list_agents()}")
