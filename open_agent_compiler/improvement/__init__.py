"""Iterative improvement loop — Phase 6.

The framework can be applied to itself: read the JSONL artifacts that
Phase 5's `oac test` writes, identify weaknesses, mutate the offending
agent/tool/skill definitions, re-compile + re-test, keep the winners.
This package contains the primitives:

- criteria.py      — OptimisationCriterion: pass-rate / score / latency / cost.
- version.py       — ComponentVersion lineage (content_hash + parent_hash + metrics).
- mutators/        — pluggable Mutator implementations.
- improvement_agent.py — a framework-compiled ImprovementAgent (Phase 6.4).
- loop.py          — IterativeLoop orchestrator.
- snapshot.py      — JSON snapshot emitter for promoted variants.

`oac improve` (Phase 6.7) is the CLI face of all of this.
"""

from open_agent_compiler.improvement.autoresearch import (
    ExecutableFactory,
    Probe,
    ProbeExecutable,
    ProbeOutcome,
    ProbeRunResult,
    build_callable_evaluator,
    metrics_from_results,
    optimize_callable,
    run_probe,
    run_probes,
)
from open_agent_compiler.improvement.criteria import (
    Criterion,
    CriterionKind,
    OptimisationCriterion,
)
from open_agent_compiler.improvement.eval_compile import (
    build_parent_mimic_prompt,
    write_test_variant_md,
)
from open_agent_compiler.improvement.long_running import (
    OpencodeEventTap,
    StreamedEvent,
    StreamingOpencodeRun,
)
from open_agent_compiler.improvement.opencode_eval import (
    OpencodeRunResult,
    OpencodeRunner,
    blocked_tool_attempts,
    blocked_tool_details,
    flailing_note,
    opencode_errors,
    subagent_dispatch_chain,
)
from open_agent_compiler.improvement.mutators import (
    ChoiceFieldMutator,
    IdentityMutator,
    LLMMutatorClient,
    LLMPromptRewriter,
    MutationContext,
    Mutator,
    NumericFieldMutator,
    OpencodeMutatorClient,
    PromptPrefixMutator,
    PromptSuffixMutator,
    TemperatureMutator,
    ToolDescriptionAppendMutator,
    ToolFormatMutator,
    ToolRuleAddMutator,
)
from open_agent_compiler.improvement.chart import (
    render_per_candidate_table,
    render_round_progression,
)
from open_agent_compiler.improvement.loop import (
    Evaluator,
    IterativeLoop,
    LoopResult,
    RoundResult,
)
from open_agent_compiler.improvement.branch import (
    BranchInvokerFactory,
    branch_component_id,
    build_branch_evaluator,
    build_branch_loop,
    build_outcome_branch_evaluator,
    build_outcome_branch_loop,
    make_branch_outcome_judge_test,
)
from open_agent_compiler.improvement.contract_gate import (
    ContractPredicate,
    ContractResult,
    RunOutcome,
    all_of,
    contract_gate,
    require_any_tool_called,
    require_artifact,
    require_outcome,
    require_subagent_dispatched,
    require_tool_called,
)
from open_agent_compiler.improvement.fleet import (
    FleetResult,
    ImprovementUnit,
    UnitOutcome,
    agent_unit,
    branch_unit,
    run_fleet,
)
from open_agent_compiler.improvement.scoring import (
    aggregate_score,
    continuous_score,
    hard_pass,
    metric_key,
    passes,
)
from open_agent_compiler.improvement.snapshot import (
    Snapshot,
    apply_promoted_to_agent,
    apply_promoted_to_skill,
    apply_promoted_to_tool,
    apply_promoted_to_tree,
    find_promoted_snapshot,
    find_promoted_snapshot_with_branch,
    list_snapshots,
    load_latest,
    load_promoted_definition,
    load_promoted_snapshot,
    promote,
    read_snapshot,
    write_round_winners,
    write_snapshot,
)
from open_agent_compiler.improvement.compile_helpers import (
    TOOL_DISCIPLINE_POSTAMBLE,
    apply_tool_discipline,
    clear_candidates,
    deps_env,
    find_project_root,
    flat_candidate_from_project_root,
    flat_candidate_name,
    tool_discipline_postamble,
    warmup_discovery,
)
from open_agent_compiler.improvement.probe_cache import (
    ProbeCache,
    ProbeResult,
    ProbeSynthesizer,
)
from open_agent_compiler.improvement.source_apply import (
    SourceApplyError,
    apply_prompt_to_source,
)
from open_agent_compiler.improvement.store import (
    RunStore,
    SqliteRunStore,
    default_store_path,
    open_store,
    register_store_scheme,
    version_from_candidate_row,
)
from open_agent_compiler.improvement.interactive_eval import (
    SpecFactory,
    build_interactive_evaluator,
    interactive_probe_executable,
    outcome_from_run,
    score_interactive_spec,
)
from open_agent_compiler.improvement.harness_eval import (
    CodexRunner,
    HarnessResult,
    HarnessRunner,
    PiRunner,
    SubprocessHarnessResult,
    get_runner,
    list_runners,
    register_runner,
)
from open_agent_compiler.improvement.split_loop import PerClassResult, run_per_class_loops
from open_agent_compiler.improvement.target_loop import (
    INTERACTIVE_HARNESS,
    EvaluatorFactory,
    OptimizationTarget,
    PerTargetResult,
    run_per_target_loops,
    targets_from_split_profile,
)
from open_agent_compiler.improvement.improvement_agent import (
    ImprovementAgentMutator,
    Invoker,
    build_improvement_agent_definition,
)
from open_agent_compiler.improvement.version import (
    ComponentKind,
    ComponentRegistry,
    ComponentVersion,
    stable_content_hash,
)

__all__ = [
    "Probe",
    "ProbeOutcome",
    "ProbeRunResult",
    "ProbeExecutable",
    "ExecutableFactory",
    "run_probe",
    "run_probes",
    "metrics_from_results",
    "build_callable_evaluator",
    "optimize_callable",
    "NumericFieldMutator",
    "ChoiceFieldMutator",
    "Criterion",
    "CriterionKind",
    "OptimisationCriterion",
    "build_parent_mimic_prompt",
    "write_test_variant_md",
    "OpencodeEventTap",
    "StreamedEvent",
    "StreamingOpencodeRun",
    "OpencodeRunResult",
    "OpencodeRunner",
    "opencode_errors",
    "subagent_dispatch_chain",
    "blocked_tool_attempts",
    "blocked_tool_details",
    "flailing_note",
    "ComponentKind",
    "ComponentRegistry",
    "ComponentVersion",
    "stable_content_hash",
    "Mutator",
    "MutationContext",
    "IdentityMutator",
    "PromptPrefixMutator",
    "PromptSuffixMutator",
    "TemperatureMutator",
    "ToolDescriptionAppendMutator",
    "ToolFormatMutator",
    "ToolRuleAddMutator",
    "LLMMutatorClient",
    "LLMPromptRewriter",
    "OpencodeMutatorClient",
    "Evaluator",
    "IterativeLoop",
    "LoopResult",
    "RoundResult",
    "BranchInvokerFactory",
    "branch_component_id",
    "build_branch_evaluator",
    "build_branch_loop",
    "make_branch_outcome_judge_test",
    "build_outcome_branch_evaluator",
    "build_outcome_branch_loop",
    "ContractPredicate",
    "ContractResult",
    "RunOutcome",
    "all_of",
    "contract_gate",
    "require_any_tool_called",
    "require_artifact",
    "require_outcome",
    "require_subagent_dispatched",
    "require_tool_called",
    "ImprovementUnit",
    "UnitOutcome",
    "FleetResult",
    "agent_unit",
    "branch_unit",
    "run_fleet",
    "render_per_candidate_table",
    "render_round_progression",
    "aggregate_score",
    "continuous_score",
    "hard_pass",
    "metric_key",
    "passes",
    "Snapshot",
    "apply_promoted_to_agent",
    "apply_promoted_to_skill",
    "apply_promoted_to_tool",
    "apply_promoted_to_tree",
    "find_promoted_snapshot",
    "find_promoted_snapshot_with_branch",
    "list_snapshots",
    "load_latest",
    "load_promoted_definition",
    "load_promoted_snapshot",
    "promote",
    "read_snapshot",
    "write_round_winners",
    "write_snapshot",
    "find_project_root",
    "flat_candidate_name",
    "flat_candidate_from_project_root",
    "clear_candidates",
    "warmup_discovery",
    "TOOL_DISCIPLINE_POSTAMBLE",
    "tool_discipline_postamble",
    "apply_tool_discipline",
    "deps_env",
    "ProbeCache",
    "ProbeResult",
    "ProbeSynthesizer",
    "PerClassResult",
    "run_per_class_loops",
    # per-target loops (harness × model_class adaptation matrix)
    "INTERACTIVE_HARNESS",
    "EvaluatorFactory",
    "OptimizationTarget",
    "PerTargetResult",
    "run_per_target_loops",
    "targets_from_split_profile",
    # run store (autoloop observability) + source apply
    "RunStore",
    "SqliteRunStore",
    "SourceApplyError",
    "apply_prompt_to_source",
    "default_store_path",
    "open_store",
    "register_store_scheme",
    "version_from_candidate_row",
    # interactive-tier evaluator (realtime runner as a target)
    "SpecFactory",
    "build_interactive_evaluator",
    "interactive_probe_executable",
    "outcome_from_run",
    "score_interactive_spec",
    # harness-agnostic eval runners
    "CodexRunner",
    "HarnessResult",
    "HarnessRunner",
    "PiRunner",
    "SubprocessHarnessResult",
    "get_runner",
    "list_runners",
    "register_runner",
    "ImprovementAgentMutator",
    "Invoker",
    "build_improvement_agent_definition",
]
