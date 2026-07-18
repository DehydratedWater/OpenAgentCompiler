from pathlib import Path
from typing import ClassVar

from open_agent_compiler.compiler.build_graph import topological_order
from open_agent_compiler.compiler.core.compiler import Compiler
from open_agent_compiler.compiler.dialects.opencode.compile_agents import compile_agent_markdown
from open_agent_compiler.compiler.dialects.opencode.compile_permissions import generate_permissions
from open_agent_compiler.compiler.dialects.opencode.compile_scripts import compile_scripts
from open_agent_compiler.model.core.agent_model import AgentVariant


class OpenCodeCompiler(Compiler):
    dialect_name: ClassVar[str] = "opencode"
    supports_features: ClassVar[frozenset[str]] = frozenset({
        "workflow",
        "subagents",
        "bundled_scripts",
        "permissions",
        "todo_modes",
        "split_profiles",
    })

    def __init__(self, target: Path, resolved_variants: dict[str, AgentVariant]):
        super().__init__(target, resolved_variants)

    def compile(self):
        self.target.mkdir(parents=True, exist_ok=True)

        all_tools = []
        for agent in self.resolved_variants.values():
            agent_tools = list(agent.agent_definition.extra_tools)
            for skill in agent.agent_definition.skills:
                for wf_step in skill.workflow_steps:
                    agent_tools.extend(wf_step.tools_used)
            all_tools.extend(agent_tools)

        compile_scripts(self.target, all_tools, variants=self.resolved_variants)

        # Parents (orchestrators) first so later phases can implement
        # stub-overwrite semantics safely; for now order is informational
        # but consistent.
        order = topological_order(self.resolved_variants)
        for slot_name in order:
            agent = self.resolved_variants[slot_name]
            permissions_dict = generate_permissions(agent)
            compile_agent_markdown(
                self.target, slot_name, agent.postfix, agent, permissions_dict,
            )
            # Dual-compile: when the slot opted in, ALSO emit a primary-
            # mode .md so the same agent is reachable via `opencode run
            # --agent <name>-primary` (or via opencode_manager.py from
            # another primary). Skip when the slot is already primary —
            # the original file would collide with itself.
            if (
                agent.also_compile_as_primary
                and agent.agent_mode != "primary"
            ):
                primary_variant = agent.model_copy(
                    update={"agent_mode": "primary"},
                )
                primary_permissions = generate_permissions(primary_variant)
                compile_agent_markdown(
                    self.target, slot_name,
                    f"{agent.postfix}-primary",
                    primary_variant, primary_permissions,
                )
