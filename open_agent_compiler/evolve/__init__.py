"""Evolve a coding harness for an existing repository — `oac evolve`.

Point the framework at a repo and get back a coding harness tailored to
it: agents + skills for the repeated work in THAT repo (/plan,
/implement, /review-pr, /fix-tests, plus repo-specific knowledge mined
from its docs, conventions, and change history), compiled for a chosen
dialect, safely isolated, and wired for autoloop evolution.

The pipeline:

1. **Isolate** (isolate.py) — clone the repo into a workspace and strip
   EVERY remote, so nothing the harness does can ever reach the real
   upstream tree.
2. **Recon** (recon.py) — build a `RepoProfile`: languages, test/build/
   lint commands, doc files, existing agent instructions (CLAUDE.md /
   AGENTS.md / skills), commit conventions, and the hot paths where the
   repeated work happens (git co-change analysis).
3. **Synthesize** (synthesize.py) — turn the profile into an OAC
   registry (planner / implementer / reviewer + skills), compile it
   INTO the isolated workspace so the agents operate on the repo, and
   write the evolution scaffolding (repo_profile.json, agents.py
   loader, evolve_loop.py, goals).
4. **Replay evaluation** (replay.py) — the fitness function: real
   commits from the repo's history are replayed as tasks against their
   parent state; the harness's diff is scored for file overlap and
   diff similarity against what the repo's humans actually wrote.
   Plugs into IterativeLoop / run_per_target_loops like any evaluator.
5. **Package** (package.py) — zip the evolved harness for handoff.

`oac evolve <repo> --out <dir>` runs 1-3 and 5; the live evolution loop
(4, needs the harness runtime + a provider) runs from the generated
`evolve_loop.py` inside the workspace.
"""

from open_agent_compiler.evolve.isolate import isolate_repo
from open_agent_compiler.evolve.package import package_harness
from open_agent_compiler.evolve.recon import RepoProfile, profile_repo
from open_agent_compiler.evolve.reference import (
    ReferenceTask,
    build_reference_evaluator,
    generate_references,
    load_references,
    output_similarity,
)
from open_agent_compiler.evolve.replay import (
    ReplayCommit,
    build_replay_evaluator,
    diff_similarity,
    file_overlap,
    select_replay_commits,
)
from open_agent_compiler.evolve.synthesize import (
    build_harness_registry,
    synthesize_harness,
)

__all__ = [
    "ReferenceTask",
    "RepoProfile",
    "ReplayCommit",
    "build_harness_registry",
    "build_reference_evaluator",
    "build_replay_evaluator",
    "diff_similarity",
    "file_overlap",
    "generate_references",
    "isolate_repo",
    "load_references",
    "output_similarity",
    "package_harness",
    "profile_repo",
    "select_replay_commits",
    "synthesize_harness",
]
