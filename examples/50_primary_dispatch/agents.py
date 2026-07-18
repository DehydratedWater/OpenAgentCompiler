"""Primary→primary dispatch via opencode_manager.py.

The "coordinator" is a primary agent. Its subagents list references a
"worker" agent in **primary mode** (not subagent mode). At runtime the
coordinator can't reach the worker via the Task tool — instead it
shells out to the bundled opencode_manager.py dispatcher, which spawns
a fresh opencode session running the worker.

Why bother? Two reasons:
1. The worker keeps a clean primary identity — it can have its own
   subagents and its own session storage; it's not a one-shot child.
2. Long-running or parallel work fans out from a coordinator without
   chewing up the parent's context window with the worker's tool
   history.

In the compiled coordinator's frontmatter you'll see
  permission.bash["uv run scripts/opencode_manager.py run --agent *"]:
  allow
and the bundled opencode_manager.py + subagent_todo.py + workspace_io.py
all land under build/scripts/ automatically (the auto-include rule sees
the primary-mode subagent reference).
"""

from __future__ import annotations

from open_agent_compiler import (
    AgentDefinition,
    AgentHeader,
    AgentRegistry,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)


def _worker() -> AgentDefinition:
    return AgentDefinition(
        header=AgentHeader(
            agent_id="number-cruncher",
            name="number-cruncher",
            description="Crunches a numerical question and returns a single number.",
        ),
        usage_explanation_long=(
            "Reads a math word problem and returns ONLY the final number"
            " (no commentary, no units beyond what the problem implied)."
        ),
        usage_explanation_short="returns one number",
        system_prompt=(
            "You are a calculation agent. Read the user's math word"
            " problem and reply with ONLY the final number. No commentary,"
            " no explanation, no leading text — just the number."
        ),
    )


def _coordinator() -> AgentDefinition:
    worker_ref = AgentHeader(
        agent_id="number-cruncher",
        name="number-cruncher",
        description="Math agent — invoke via bash.",
        mode="primary",  # ← bash dispatch via opencode_manager, NOT Task
    )
    return AgentDefinition(
        header=AgentHeader(
            agent_id="math-coordinator",
            name="math-coordinator",
            description="Decomposes a question + dispatches math sub-questions.",
        ),
        usage_explanation_long=(
            "Reads a multi-part word problem. Decomposes it into discrete"
            " numerical questions and dispatches each to the"
            " number-cruncher worker via the opencode_manager bash"
            " dispatcher. Assembles the workers' replies into the final"
            " answer."
        ),
        usage_explanation_short="math problem decomposer",
        subagents=[worker_ref],
        system_prompt=(
            "You are the math coordinator.\n"
            "\n"
            "When the user gives you a multi-part word problem:\n"
            "1. Identify each discrete numerical sub-question.\n"
            "2. For each, invoke the worker via bash:\n"
            "   `uv run scripts/opencode_manager.py run --agent"
            " number-cruncher \"<sub-question>\"`\n"
            "3. The worker returns ONLY a number for each call. Collect"
            " the numbers in order.\n"
            "4. Assemble the final answer combining the numbers per the"
            " original question's instructions.\n"
            "\n"
            "Always use the bash dispatcher — never try to do the math"
            " yourself."
        ),
    )


def registry() -> AgentRegistry:
    reg = AgentRegistry()

    coord_id = reg.register_agent(
        "math-coordinator", _coordinator(),
        ModelParameters(model_name="zai-coding-plan/glm-5.1", temperature=0.2),
    )
    worker_id = reg.register_agent(
        "number-cruncher", _worker(),
        ModelParameters(model_name="zai-coding-plan/glm-4.5-air", temperature=0.0),
    )

    reg.register_template(
        TemplateTree(
            name="tpl",
            slots=[
                TemplateSlot(name="primary", default_agent_id=coord_id),
                # The worker slot's name is NOT 'primary' so it would
                # default to subagent mode in resolve_config. To compile
                # it as a primary agent (which opencode_manager expects),
                # this slot is named 'primary-worker' but we manually
                # set agent_mode below before the compile.
                TemplateSlot(name="number-cruncher", default_agent_id=worker_id),
            ],
        )
    )
    reg.create_compilation_config(
        CompilationConfig(name="prod", template_name="tpl"),
    )
    return reg
