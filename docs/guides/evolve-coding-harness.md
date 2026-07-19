# Evolve a Coding Harness (`oac evolve`)

Point the framework at a repository and get back a **coding harness
tailored to it**: agents and skills for the repeated work in that repo,
compiled for your harness of choice, safely isolated from the real
upstream, and wired to evolve itself against two grounded fitness
signals — the repo's own history and a stronger-model teacher.

```bash
oac evolve ~/code/myrepo --out evolved_myrepo --dialect opencode
oac evolve ~/code/myrepo -i        # interactive setup
```

## What you get

```
evolved_myrepo/
└── myrepo/                     # isolated clone — NO git remotes
    ├── <the repo's files>
    ├── .opencode/agents/       # planner / implementer / reviewer (compiled)
    ├── .opencode/skills/       # OAC developer skills (self-teaching workspace)
    ├── .claude/skills/
    └── .oac-harness/
        ├── repo_profile.json   # what recon learned about the repo
        ├── agents.py           # registry loader (+ candidate override hook)
        ├── build_harness.py    # recompile
        ├── evolve_loop.py      # commit-replay evolution
        ├── teacher_eval.py     # teacher-gap evolution
        └── README.md
evolved_myrepo.zip              # the handoff artifact
```

## The pipeline

1. **Isolate** — `git clone --no-hardlinks`, then every remote is
   removed (and `assert_isolated` re-checks before every replay run).
   The harness can commit, reset, and experiment freely; nothing can
   reach the upstream tree. The zip keeps the remoteless `.git` so
   evolution still works after unzipping.
2. **Recon** — deterministic analysis into a `RepoProfile`: languages,
   test/build/lint commands (pyproject/package.json/Cargo/Makefile…),
   docs, existing agent instructions (CLAUDE.md, skills), commit
   conventions, and the **hot paths** where the repeated work happens
   (git co-change frequency).
3. **Synthesize** — the profile becomes a three-agent harness
   (`planner` / `implementer` / `reviewer`) with core skills (/plan,
   /implement, /review-pr, /fix-tests) plus repo-specific knowledge
   skills, all with the repo's real commands and conventions baked into
   the prompts. The OAC developer skill bundles (including
   **autoloop-interview** and **optimization-targets**) are deployed
   into the workspace, so a coding agent working there can set up and
   extend the whole autoloop structure itself.
4. **Evolve** — two loops, both recording to the run store and
   promoting winners:

### Fitness signal 1: commit replay (`evolve_loop.py`)

Real commits from the repo's history are replayed as tasks: the
implementer gets the commit's message against the **parent** state, and
its diff is scored against what actually shipped —

```
score = 0.5 · file-overlap (Jaccard) + 0.5 · diff-similarity (SequenceMatcher)
```

Small/medium commits are selected automatically
(`select_replay_commits`); the workspace is restored after every probe.
This measures exactly what you want the harness to be: *does it change
this repo the way this repo's humans do?*

### Fitness signal 2: the teacher gap (`teacher_eval.py`)

An autoloop can only find what its mutators propose. The teacher run
breaks that ceiling: the **same harness** runs example sessions once on
a stronger model (`--reference-model`, e.g. `glm-5.2`), those outputs
become the reference, and the evolving (cheaper) harness is scored by
similarity to them. The gap feeds back into mutation:

- `TeacherGapRewriter` — the LLM rewriter sees the worst
  teacher/student divergence (excerpts of both) and adapts the prompt
  toward the *general capability* the teacher displayed.
- `LLMWorkflowEditor` — **structural** evolution: the LLM may add,
  remove, or reorder workflow steps (validated JSON, renumbered,
  rejected if malformed) to close behaviors prompt text can't express.

### Structural mutation beyond the LLM

Deterministic structural mutators let you propose specific hypotheses
in any loop, not just evolve harnesses:

```python
from open_agent_compiler.improvement import (
    WorkflowStepAppendMutator, WorkflowStepRemoveMutator,
    ToolAttachMutator, ToolDetachMutator,
)

WorkflowStepAppendMutator({"name": "Re-verify",
                           "instructions": "Run the tests once more."})
ToolDetachMutator("legacy-tool")
```

The loop keeps a structural change only if the fitness signal actually
improves — "should the agent verify twice?" becomes an experiment, not
an opinion. Your `registry_factory` must apply the mutated fields when
rebuilding candidates; the generated harness loader
(`.oac-harness/agents.py`) applies `system_prompt` and `workflow`
overrides out of the box.

## Safety model

- The workspace clone has **no remotes**; `assert_isolated` guards
  every replay.
- Replay checkouts always restore the original ref; untracked harness
  files survive cleanup (`git clean` exclusion list).
- The zip is push-safe by construction (the `.git` inside has no
  remotes); pass `include_git=False` to `package_harness` for a lighter
  artifact.

## See also

- [Optimization targets](optimization-targets.md) — the loop machinery
  the evolve preset builds on
- `open_agent_compiler/evolve/` — the implementation
- `oac evolve --help` — all flags (`--dialect`, `--model`,
  `--reference-model`, `--commits`, `--skills`, `--zip`, `-i`)
