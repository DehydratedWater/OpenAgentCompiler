"""Mutators: produce candidate ComponentVersions from a starting version.

Each mutator takes a ComponentVersion + a MutationContext and returns
EITHER a new ComponentVersion (parent_hash linked to the input) OR None
when the mutator doesn't apply to that input.

Bundled implementations:

- IdentityMutator: returns the input unchanged. Useful as a control in
  the loop's Pareto evaluation, and as a regression check.
- PromptPrefixMutator / PromptSuffixMutator: deterministic; nudges the
  system_prompt with a fixed string.
- TemperatureMutator: adjusts an agent's sampling temperature within
  bounds.
- LLMPromptRewriter (Phase 6.4): asks a model to rewrite the prompt
  given the failure context.

Users register their own by subclassing Mutator + adding to a list the
IterativeLoop iterates through.
"""

from open_agent_compiler.improvement.mutators.base import Mutator, MutationContext
from open_agent_compiler.improvement.mutators.deterministic import (
    IdentityMutator,
    PromptPrefixMutator,
    PromptSuffixMutator,
    TemperatureMutator,
    ToolDescriptionAppendMutator,
    ToolFormatMutator,
    ToolRuleAddMutator,
)
from open_agent_compiler.improvement.mutators.fields import (
    ChoiceFieldMutator,
    NumericFieldMutator,
)
from open_agent_compiler.improvement.mutators.llm import LLMMutatorClient, LLMPromptRewriter
from open_agent_compiler.improvement.mutators.structural import (
    LLMWorkflowEditor,
    ToolAttachMutator,
    ToolDetachMutator,
    WorkflowStepAppendMutator,
    WorkflowStepRemoveMutator,
)
from open_agent_compiler.improvement.mutators.teacher_gap import TeacherGapRewriter
from open_agent_compiler.improvement.mutators.opencode_teacher import (
    OpencodeMutatorClient,
    install_teacher_agent,
    normalize_model_ref,
    teacher_agent_name,
)
from open_agent_compiler.improvement.mutators.sectioned import (
    SectionRewriterMutator,
    make_section_mutators,
)
from open_agent_compiler.improvement.mutators.tool_selection import (
    ToolSelectionAction,
    ToolSelectionMutator,
    ToolSequenceMutator,
)

__all__ = [
    "SectionRewriterMutator",
    "make_section_mutators",
    "Mutator",
    "MutationContext",
    "IdentityMutator",
    "NumericFieldMutator",
    "ChoiceFieldMutator",
    "PromptPrefixMutator",
    "PromptSuffixMutator",
    "TemperatureMutator",
    "ToolDescriptionAppendMutator",
    "ToolFormatMutator",
    "ToolRuleAddMutator",
    "ToolSelectionAction",
    "ToolSelectionMutator",
    "ToolSequenceMutator",
    "LLMMutatorClient",
    "LLMPromptRewriter",
    "LLMWorkflowEditor",
    "TeacherGapRewriter",
    "ToolAttachMutator",
    "ToolDetachMutator",
    "WorkflowStepAppendMutator",
    "WorkflowStepRemoveMutator",
    "OpencodeMutatorClient",
    "normalize_model_ref",
    "teacher_agent_name",
    "install_teacher_agent",
]
