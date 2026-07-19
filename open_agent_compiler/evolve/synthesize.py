"""Harness synthesis — RepoProfile → agents + skills, compiled into the repo.

The synthesized harness is deliberately a STARTING POINT with the repo's
facts baked in (test/lint/build commands, conventions, hot paths, doc
pointers) — the evolution loop and the resident coding agent grow it
from there. Three agents cover the repeated work:

- `planner` (subagent) — turns a task into a step plan referencing the
  repo's real structure.
- `implementer` (primary) — the workhorse: plan → implement → verify,
  delegating to planner/reviewer.
- `reviewer` (subagent) — reviews diffs the way this repo reviews PRs.

Skills: /plan, /implement, /review-pr, /fix-tests plus the
repo-specific knowledge skills (conventions, hot areas). Everything is
registered through one factory (`build_harness_registry`) that takes
the profile, so the harness can be rebuilt from repo_profile.json
without re-running recon.
"""

from __future__ import annotations

from pathlib import Path

from open_agent_compiler.compiler.script import CompileScript
from open_agent_compiler.evolve.recon import RepoProfile
from open_agent_compiler.model.core.agent_model import (
    AgentDefinition,
    AgentHeader,
    CompilationConfig,
    ModelParameters,
    TemplateSlot,
    TemplateTree,
)
from open_agent_compiler.model.core.agent_registry import AgentRegistry
from open_agent_compiler.model.core.skills_model import SkillDefinition, WorkflowStep
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition

HARNESS_DIR = ".oac-harness"


def _repo_facts(profile: RepoProfile) -> str:
    lines = [f"Repository: {profile.name} (primary language: {profile.primary_language})."]
    if profile.test_command:
        lines.append(f"Run tests with: `{profile.test_command}`.")
    if profile.lint_command:
        lines.append(f"Lint with: `{profile.lint_command}`.")
    if profile.build_command:
        lines.append(f"Build with: `{profile.build_command}`.")
    if profile.conventional_commits:
        lines.append("Commit messages follow Conventional Commits"
                     " (type(scope): subject).")
    if profile.hot_paths:
        lines.append("Most work happens under: "
                     + ", ".join(f"`{p}`" for p in profile.hot_paths[:6]) + ".")
    if profile.doc_files:
        lines.append("Read first: " + ", ".join(profile.doc_files) + ".")
    if profile.agent_instructions:
        lines.append("Existing agent instructions to honor: "
                     + ", ".join(profile.agent_instructions) + ".")
    return "\n".join(lines)


def _skill(name: str, short: str, long: str, steps: list[tuple[str, str]]) -> SkillDefinition:
    return SkillDefinition(
        name=name, description=short,
        usage_explanation_long=long, usage_explanation_short=short,
        rules=[],
        workflow_steps=[
            WorkflowStep(header=header, condition=None, result=None,
                         rule=rule, tools_used=[])
            for header, rule in steps
        ],
        positive_examples=[], negative_examples=[],
    )


def _core_skills(profile: RepoProfile) -> list[SkillDefinition]:
    test = profile.test_command or "the project's test suite"
    lint = profile.lint_command or "the project's linter"
    skills = [
        _skill(
            "plan", "turn a task into a concrete step plan",
            "Break a feature/bug task into ordered, verifiable steps"
            " grounded in this repo's real files.",
            [("Locate", "find the files involved — start from the hot paths"
                        " and the docs listed in your prompt"),
             ("Decompose", "list the minimal ordered edits, each with its"
                           " verification step"),
             ("Risks", "name what could break and which tests cover it")],
        ),
        _skill(
            "implement", "make the planned change the way this repo does",
            "Apply a plan step by step, matching the surrounding code's"
            " style, and verify continuously.",
            [("Edit", "smallest coherent change per step; mirror the"
                      " neighboring code's idioms"),
             ("Verify", f"after each step run {test}"),
             ("Lint", f"before finishing run {lint}")],
        ),
        _skill(
            "review-pr", "review a diff the way this repo reviews PRs",
            "Review changes for correctness, repo-idiom fit, and missing"
            " tests — concrete findings only.",
            [("Correctness", "trace each changed path for behavior"
                             " regressions and edge cases"),
             ("Idioms", "flag anything that doesn't look like the"
                        " surrounding code or the repo's conventions"),
             ("Tests", "every behavior change needs a covering test —"
                       " name the missing ones")],
        ),
        _skill(
            "fix-tests", "diagnose and fix failing tests",
            "Reproduce the failure, find the true cause, fix code-or-test"
            " deliberately.",
            [("Reproduce", f"run {test} and capture the exact failure"),
             ("Diagnose", "decide: regression in code, or stale test?"),
             ("Fix", "apply the smallest fix; rerun until green")],
        ),
    ]
    if profile.hot_paths:
        skills.append(_skill(
            "repo-hot-areas", "where the repeated work in this repo lives",
            "The areas that change most often — and therefore where most"
            " tasks land: " + ", ".join(profile.hot_paths[:8]) + ".",
            [("Orient", "when a task doesn't name files, check these"
                        " areas first")],
        ))
    return skills


def build_harness_registry(
    profile: RepoProfile,
    *,
    model_name: str = "zai-coding-plan/glm-4.5-air",
) -> AgentRegistry:
    """The evolved-harness registry: planner + implementer + reviewer."""
    facts = _repo_facts(profile)
    reg = AgentRegistry()

    planner = AgentDefinition(
        header=AgentHeader(agent_id="planner", name="planner",
                           description="Plans changes for this repo."),
        usage_explanation_long="Turns a task into an ordered step plan.",
        usage_explanation_short="plans",
        system_prompt=(
            "You plan changes for this repository. Produce a numbered,"
            " verifiable step plan — files to touch, edits per file, how"
            f" each step is verified.\n\n{facts}"
        ),
        model_class="analytical",
        todo_mode="none",
    )
    reviewer = AgentDefinition(
        header=AgentHeader(agent_id="reviewer", name="reviewer",
                           description="Reviews diffs for this repo."),
        usage_explanation_long="Reviews changes for correctness and idiom fit.",
        usage_explanation_short="reviews",
        system_prompt=(
            "You review diffs for this repository the way its maintainers"
            " review PRs: correctness first, then idiom fit, then missing"
            f" tests. Concrete findings only.\n\n{facts}"
        ),
        model_class="analytical",
        todo_mode="none",
    )
    implementer = AgentDefinition(
        header=AgentHeader(agent_id="implementer", name="implementer",
                           description="Implements changes in this repo."),
        usage_explanation_long="Plans, implements, verifies, self-reviews.",
        usage_explanation_short="implements",
        system_prompt=(
            "You implement changes in this repository, matching its"
            f" existing style and workflows.\n\n{facts}"
        ),
        subagents=[
            AgentHeader(agent_id="planner", name="planner",
                        description="Plans changes for this repo.",
                        mode="subagent"),
            AgentHeader(agent_id="reviewer", name="reviewer",
                        description="Reviews diffs for this repo.",
                        mode="subagent"),
        ],
        workflow=[
            WorkflowStepDefinition(
                id=1, name="Plan",
                instructions="Spawn the planner on the task; follow its plan.",
                subagents=("planner",),
            ),
            WorkflowStepDefinition(
                id=2, name="Implement",
                instructions=(
                    "Apply the plan step by step (use the implement skill);"
                    " verify after each step."
                ),
            ),
            WorkflowStepDefinition(
                id=3, name="Review",
                instructions=(
                    "Spawn the reviewer on your diff; address every finding"
                    " before declaring done."
                ),
                subagents=("reviewer",),
            ),
        ],
        skills=_core_skills(profile),
        todo_mode="strict",
    )

    ids = {}
    for agent in (planner, reviewer, implementer):
        ids[agent.header.agent_id] = reg.register_agent(
            agent.header.agent_id, agent,
            ModelParameters(model_name=model_name, temperature=0.3),
        )
    reg.register_template(TemplateTree(
        name="harness",
        slots=[
            TemplateSlot(name="implementer", default_agent_id=ids["implementer"]),
            TemplateSlot(name="planner", default_agent_id=ids["planner"]),
            TemplateSlot(name="reviewer", default_agent_id=ids["reviewer"]),
        ],
    ))
    reg.create_compilation_config(
        CompilationConfig(name="harness", template_name="harness"))
    return reg


def synthesize_harness(
    workspace_repo: Path,
    profile: RepoProfile,
    *,
    dialect: str = "opencode",
    model_name: str = "zai-coding-plan/glm-4.5-air",
    reference_model: str = "zai-coding-plan/glm-5.2",
    replay_commits: int = 5,
    native_tools: bool = False,
    skills: tuple[str, ...] = ("opencode", "claude"),
) -> list[Path]:
    """Compile the harness INTO the isolated repo + write evolution files.

    Returns the paths written under `<repo>/.oac-harness/` (the compiled
    agent tree lands at the repo root so the agents operate on the repo).

    `skills` deploys the OAC developer skill bundles (incl.
    optimization-targets and autoloop-interview) into the workspace, so
    a coding agent (Claude Code / opencode / Codex) working THERE knows
    how to set up the whole autoloop structure and run the evolution —
    the workspace is self-teaching.
    """
    registry = build_harness_registry(profile, model_name=model_name)
    CompileScript(
        target=workspace_repo,
        factory=lambda: registry,
        config="harness",
        dialect=dialect,
        native_tools=native_tools,
    ).run()

    if skills:
        from open_agent_compiler.skills import (
            emit_claude, emit_codex, emit_opencode, emit_pi, list_skills,
        )
        emitters = {"opencode": emit_opencode, "claude": emit_claude,
                    "pi": emit_pi, "codex": emit_codex}
        bundles = list_skills()
        for name in skills:
            if name in emitters:
                emitters[name](bundles, workspace_repo, force=True)

    harness_dir = workspace_repo / HARNESS_DIR
    harness_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _write(name: str, content: str) -> None:
        path = harness_dir / name
        path.write_text(content)
        written.append(path)

    _write("repo_profile.json", profile.to_json() + "\n")
    _write("agents.py", _AGENTS_LOADER.format(model_name=model_name))
    _write("build_harness.py", _BUILD_SCRIPT.format(dialect=dialect))
    _write("evolve_loop.py", _EVOLVE_LOOP.format(
        dialect=dialect, replay_commits=replay_commits,
    ))
    _write("teacher_eval.py", _TEACHER_EVAL.format(
        dialect=dialect, reference_model=reference_model,
    ))
    _write("README.md", _HARNESS_README.format(
        name=profile.name, dialect=dialect,
        run_command=_run_command_hint(dialect),
        test_command=profile.test_command or "(none detected)",
    ))
    return written


def _run_command_hint(dialect: str) -> str:
    """The dialect-correct way to drive the implementer on a task."""
    return {
        "opencode": 'opencode run --agent implementer "Add …"',
        "pi": 'pi -p --approve "Use the Agent tool to spawn the implementer'
              ' agent: Add …"',
        "claude": 'claude -p "Use the implementer subagent: Add …"',
        "codex": 'codex exec "Spawn the implementer agent as a subagent:'
                 ' Add …"',
    }.get(dialect, f"# drive the implementer via your {dialect} runtime")


_AGENTS_LOADER = '''\
"""Harness registry loader — rebuilds the registry from repo_profile.json.

`oac compile/test/improve .oac-harness.agents:registry` works from the
workspace root. Edit repo_profile.json (or this file) to steer the
harness; the evolve loops mutate on top — not just the prompt: the
`overrides` hook also applies structural mutations (workflow steps,
extra tools), so WorkflowStepAppendMutator / LLMWorkflowEditor /
ToolAttachMutator candidates compile for real.
"""

from pathlib import Path

from open_agent_compiler.evolve import RepoProfile, build_harness_registry
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition

HERE = Path(__file__).resolve().parent


def registry(system_prompt: str | None = None, overrides: dict | None = None):
    profile = RepoProfile.from_json((HERE / "repo_profile.json").read_text())
    reg = build_harness_registry(profile, model_name="{model_name}")
    merged = dict(overrides or {{}})
    if system_prompt:
        merged["system_prompt"] = system_prompt
    if merged:
        variant = reg.get_agent(
            [a for a in reg.list_agents() if "implementer" in a][0])
        updates: dict = {{}}
        if merged.get("system_prompt"):
            updates["system_prompt"] = merged["system_prompt"]
        if merged.get("workflow"):
            updates["workflow"] = [
                WorkflowStepDefinition(**{{k: v for k, v in step.items()}})
                for step in merged["workflow"]
            ]
        variant.agent_definition = variant.agent_definition.model_copy(
            update=updates)
    return reg
'''

_BUILD_SCRIPT = '''\
"""Recompile the harness into the workspace repo root."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from open_agent_compiler.compiler.script import CompileScript  # noqa: E402

sys.path.insert(0, str(HERE))
from agents import registry  # noqa: E402

CompileScript(
    target=HERE.parent, factory=registry, config="harness",
    dialect="{dialect}", verbose=True,
).run()
'''

_EVOLVE_LOOP = '''\
"""Evolve the harness against this repo's own history (commit replay).

Real commits are replayed as tasks: the implementer gets each commit's
message against the parent state, and its diff is scored for file
overlap + similarity to what the repo's humans actually wrote. Winners
promote; history records to .oac/improvement.db.

Needs the "{dialect}" runtime installed and a configured provider.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(HERE))

from agents import registry  # noqa: E402
from open_agent_compiler.evolve import (  # noqa: E402
    build_replay_evaluator, select_replay_commits,
)
from open_agent_compiler.improvement import (  # noqa: E402
    Criterion, IdentityMutator, IterativeLoop, OptimisationCriterion,
    PromptPrefixMutator, WorkflowStepAppendMutator, open_store,
    write_snapshot, promote,
)
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402


def main() -> None:
    commits = select_replay_commits(WORKSPACE, n={replay_commits})
    if not commits:
        raise SystemExit("no replayable commits found (need git history)")
    print(f"replaying {{len(commits)}} commit(s):")
    for c in commits:
        print(f"  {{c.sha[:10]}} {{c.subject[:60]}}")

    baseline_reg = registry()
    implementer = baseline_reg.get_agent(
        [a for a in baseline_reg.list_agents() if "implementer" in a][0])
    defn = implementer.agent_definition
    baseline = ComponentVersion.of(
        component_id="implementer", kind="agent",
        definition={{
            "system_prompt": defn.system_prompt,
            "workflow": [s.model_dump() for s in defn.workflow],
        }},
    )
    store = open_store(project_root=WORKSPACE)
    loop = IterativeLoop(
        baseline=baseline,
        mutators=[
            IdentityMutator(),
            PromptPrefixMutator("Match this repository's existing"
                                " patterns exactly. "),
            # Structural hypothesis: an extra verification pass. The loop
            # keeps it only if replay similarity actually improves.
            WorkflowStepAppendMutator({{
                "name": "Re-verify",
                "instructions": "Run the test suite once more and re-read"
                                " your full diff before finishing.",
            }}),
        ],
        criterion=OptimisationCriterion(
            name="replay-similarity",
            criteria=(Criterion(kind="score_mean", target=0.5, hard=False),),
        ),
        evaluator=build_replay_evaluator(
            WORKSPACE, commits,
            registry_factory=lambda d: registry(overrides=d),
            dialect="{dialect}",
            agent_name="implementer",
        ),
        max_rounds=2, frontier_size=2, store=store,
    )
    result = loop.run()
    best = result.best(metric="score_mean")
    if best is None:
        raise SystemExit("no winner")
    snap_path = write_snapshot(best, WORKSPACE / "improved")
    promote(snap_path, WORKSPACE, force=True, store=store)
    print(f"winner {{best.content_hash[:12]}} score_mean="
          f"{{best.metrics.get('score_mean', 0):.3f}} promoted")


if __name__ == "__main__":
    main()
'''

_TEACHER_EVAL = '''\
"""Teacher-gap evolution: compare this harness to itself on a STRONGER model.

The autoloop can only find what its mutators propose; a stronger model
running the SAME harness shows behaviors the loop never discovered by
itself. This script: (1) runs the example tasks once with the teacher
({reference_model}) and stores the reference outputs, (2) evolves the
student prompt with TeacherGapRewriter — the LLM rewriter sees the
worst teacher/student divergence each round and adapts the prompt to
close the gap.

Edit TASKS below to real sessions from your workflow, then:

    uv run python .oac-harness/teacher_eval.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(HERE))

from agents import registry  # noqa: E402
from open_agent_compiler.evolve import (  # noqa: E402
    ReferenceTask, RepoProfile, build_harness_registry,
    build_reference_evaluator, generate_references, load_references,
)
from open_agent_compiler.improvement import (  # noqa: E402
    Criterion, IdentityMutator, IterativeLoop, LLMWorkflowEditor,
    MutationContext, OpenAICompatMutatorClient, OptimisationCriterion,
    TeacherGapRewriter, open_store, promote, write_snapshot,
)
from open_agent_compiler.improvement.version import ComponentVersion  # noqa: E402

TASKS = [
    ReferenceTask(task_id="example-1",
                  prompt="TODO: a realistic task from this repo's workflow"),
    ReferenceTask(task_id="example-2",
                  prompt="TODO: another representative session"),
]

REFS_PATH = HERE / "reference_outputs.json"


def main() -> None:
    profile = RepoProfile.from_json((HERE / "repo_profile.json").read_text())

    if REFS_PATH.exists():
        references = load_references(REFS_PATH)
        print(f"loaded {{len(references)}} reference output(s)")
    else:
        print("generating teacher references with {reference_model} …")
        references = generate_references(
            WORKSPACE, TASKS,
            registry=build_harness_registry(
                profile, model_name="{reference_model}"),
            dialect="{dialect}", out_path=REFS_PATH,
        )
        print(f"stored {{len(references)}} reference output(s) -> {{REFS_PATH}}")

    baseline_reg = registry()
    implementer = baseline_reg.get_agent(
        [a for a in baseline_reg.list_agents() if "implementer" in a][0])
    defn = implementer.agent_definition
    baseline = ComponentVersion.of(
        component_id="implementer", kind="agent",
        definition={{
            "system_prompt": defn.system_prompt,
            "workflow": [s.model_dump() for s in defn.workflow],
        }},
    )

    gaps: dict = {{}}
    evaluator = build_reference_evaluator(
        WORKSPACE, TASKS, references,
        registry_factory=lambda d: registry(overrides=d),
        dialect="{dialect}", gap_sink=gaps,
    )
    # The rewriter LLM: OAC_MUTATOR_MODEL / OAC_MUTATOR_BASE_URL /
    # OAC_MUTATOR_API_KEY env vars (falling back to LIVE_*). Without a
    # configured model the LLM-driven mutators skip and only the
    # deterministic mutators run.
    llm = OpenAICompatMutatorClient.from_env()
    if llm is None:
        print("note: no OAC_MUTATOR_MODEL/LIVE_MODEL_ID configured —"
              " running with deterministic mutators only")
    ctx = MutationContext(llm=llm)
    store = open_store(project_root=WORKSPACE)
    loop = IterativeLoop(
        baseline=baseline,
        mutators=[
            IdentityMutator(),
            # Prompt adaptation from the worst teacher/student gap …
            TeacherGapRewriter(gap_source=lambda: gaps),
            # … and STRUCTURAL adaptation: the LLM may add/remove/reorder
            # workflow steps to close behaviors the teacher displayed.
            LLMWorkflowEditor(gap_source=lambda: gaps),
        ],
        criterion=OptimisationCriterion(
            name="teacher-gap",
            criteria=(Criterion(kind="score_mean", target=0.7, hard=False),),
        ),
        evaluator=evaluator,
        max_rounds=3, frontier_size=2,
        mutation_context=ctx, store=store,
    )
    result = loop.run()
    best = result.best(metric="score_mean")
    if best is None:
        raise SystemExit("no winner")
    snap_path = write_snapshot(best, WORKSPACE / "improved")
    promote(snap_path, WORKSPACE, force=True, store=store)
    print(f"winner {{best.content_hash[:12]}} score_mean="
          f"{{best.metrics.get('score_mean', 0):.3f}} promoted")


if __name__ == "__main__":
    main()
'''

_HARNESS_README = '''\
# Evolved coding harness for `{name}`

Generated by `oac evolve`. This workspace is a FULLY ISOLATED copy of
the repository (no git remotes — nothing here can reach the upstream).

## Layout

- repo files — the isolated copy the agents work on
- compiled harness at the repo root (dialect: {dialect})
- `.oac-harness/` — this directory: profile, registry loader,
  build + evolve scripts

## Use it

```bash
# drive the implementer on a task (dialect: {dialect})
cd <this workspace>
{run_command}

# recompile after editing the profile/registry
uv run python .oac-harness/build_harness.py

# evolve against the repo's own history (commit replay)
uv run python .oac-harness/evolve_loop.py
uv run oac versions list implementer
```

Detected test command: `{test_command}`

The harness judges itself two ways:

- **Commit replay** (`evolve_loop.py`) — the implementer gets a past
  commit's message against its parent state; its diff is scored for
  similarity to what was actually shipped.
- **Teacher gap** (`teacher_eval.py`) — the same harness runs example
  sessions on a STRONGER model once; the evolving prompt is scored
  against those references and rewritten toward the behaviors the
  teacher displayed that the loop never discovered by itself
  (`TeacherGapRewriter`).

## Growing the harness

The OAC developer skill bundles are deployed in this workspace
(`.opencode/skills/`, `.claude/skills/`) — a coding agent working here
already knows the framework. Useful asks:

- "interview me for the autoloop goals" (autoloop-interview skill) —
  refine what the harness optimizes beyond commit replay,
- "add a /release skill based on how this repo ships" — extend
  `.oac-harness/agents.py` with more repo-specific skills,
- "tune the implementer per target" (optimization-targets skill).
'''
