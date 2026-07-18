"""compile_scripts auto-include: bundled infrastructure based on tree features."""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.compiler.dialects.opencode.compile_scripts import (
    bundled_scripts_required,
    copy_bundled_scripts,
)
from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    AgentVariant,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition


def _variant(**defn_kwargs) -> AgentVariant:
    return AgentVariant(
        postfix="", agent_mode="primary",
        agent_definition=AgentDefinition(
            header=AgentHeader(agent_id="x", name="x", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
            **defn_kwargs,
        ),
        model_parameters=ModelParameters(model_name="m", temperature=0.0),
    )


# ---- which scripts are needed -------------------------------------------


def test_bare_agent_needs_no_bundled_scripts() -> None:
    assert bundled_scripts_required({"a": _variant()}) == []


def test_workflow_with_todo_strict_needs_subagent_todo() -> None:
    out = bundled_scripts_required({
        "a": _variant(
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
            todo_mode="strict",
        ),
    })
    assert "subagent_todo.py" in out


def test_workflow_with_todo_none_skips_subagent_todo() -> None:
    out = bundled_scripts_required({
        "a": _variant(
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
            todo_mode="none",
        ),
    })
    assert "subagent_todo.py" not in out


def test_workspace_set_needs_workspace_io() -> None:
    out = bundled_scripts_required({
        "a": _variant(workspace=".agent_workspace/{name}"),
    })
    assert "workspace_io.py" in out


def test_primary_subagent_needs_opencode_manager() -> None:
    out = bundled_scripts_required({
        "a": _variant(
            subagents=[
                AgentHeader(agent_id="b", name="workflows/big",
                            description="d", mode="primary"),
            ],
        ),
    })
    assert "opencode_manager.py" in out


def test_task_subagent_does_not_pull_opencode_manager() -> None:
    out = bundled_scripts_required({
        "a": _variant(
            subagents=[
                AgentHeader(agent_id="b", name="persona/quick",
                            description="d", mode="subagent"),
            ],
        ),
    })
    assert "opencode_manager.py" not in out


def test_all_three_when_full_featured_tree() -> None:
    tree = {
        "orch": _variant(
            workflow=[WorkflowStepDefinition(id=1, name="Step")],
            todo_mode="strict",
            workspace=".agent_workspace/{name}",
            subagents=[
                AgentHeader(agent_id="b", name="workflows/big",
                            description="d", mode="primary"),
            ],
        ),
    }
    assert set(bundled_scripts_required(tree)) == {
        "subagent_todo.py", "workspace_io.py", "opencode_manager.py",
    }


# ---- copy behavior ------------------------------------------------------


def test_copy_bundled_writes_files_to_target_scripts(tmp_target: Path) -> None:
    written = copy_bundled_scripts(tmp_target, ["subagent_todo.py", "workspace_io.py"])
    assert len(written) == 2
    assert (tmp_target / "scripts" / "subagent_todo.py").exists()
    assert (tmp_target / "scripts" / "workspace_io.py").exists()
    # Sanity: the copied file is a real script (has the bundled docstring).
    body = (tmp_target / "scripts" / "subagent_todo.py").read_text()
    assert "Subagent Todo Manager" in body


def test_unknown_bundled_script_name_raises(tmp_target: Path) -> None:
    import pytest as _pytest
    with _pytest.raises(FileNotFoundError, match="not found"):
        copy_bundled_scripts(tmp_target, ["ghost_script.py"])


# ---- end-to-end through CompileScript -----------------------------------


def _factory_with_workflow():
    reg = AgentRegistry()
    agent = AgentDefinition(
        header=AgentHeader(agent_id="x", name="orch", description=None),
        usage_explanation_long="l", usage_explanation_short="s",
        workflow=[WorkflowStepDefinition(id=1, name="Triage")],
        workspace=".agent_workspace/{name}",
        todo_mode="strict",
    )
    agent_id = reg.register_agent(
        "orch", agent, ModelParameters(model_name="m", temperature=0.0)
    )
    reg.register_template(
        TemplateTree(
            name="t",
            slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
        )
    )
    reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
    return reg


def test_compile_auto_copies_bundled_scripts_into_target(tmp_target: Path) -> None:
    CompileScript(
        target=tmp_target, factory=_factory_with_workflow, config="c",
    ).run()
    assert (tmp_target / "scripts" / "subagent_todo.py").exists()
    assert (tmp_target / "scripts" / "workspace_io.py").exists()
    # No primary subagents → no opencode_manager.
    assert not (tmp_target / "scripts" / "opencode_manager.py").exists()


def test_compile_skips_all_bundled_when_tree_doesnt_need_them(
    tmp_target: Path,
) -> None:
    def factory():
        reg = AgentRegistry()
        agent = AgentDefinition(
            header=AgentHeader(agent_id="x", name="orch", description=None),
            usage_explanation_long="l", usage_explanation_short="s",
        )
        agent_id = reg.register_agent(
            "orch", agent, ModelParameters(model_name="m", temperature=0.0)
        )
        reg.register_template(
            TemplateTree(
                name="t",
                slots=[TemplateSlot(name="primary", default_agent_id=agent_id)],
            )
        )
        reg.create_compilation_config(CompilationConfig(name="c", template_name="t"))
        return reg

    CompileScript(target=tmp_target, factory=factory, config="c").run()
    scripts_in_target = list((tmp_target / "scripts").iterdir())
    assert scripts_in_target == []
