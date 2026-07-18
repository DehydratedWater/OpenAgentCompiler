
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

from open_agent_compiler.model.core.permissions_model import ToolPermission
from open_agent_compiler.model.core.skills_model import SkillDefinition
from open_agent_compiler.model.core.test_model import AgentTest, CapabilityTest, ToolTest
from open_agent_compiler.model.core.tools_model import ToolDefinition
from open_agent_compiler.model.core.workflow_model import WorkflowStepDefinition

AgentMode = Literal['primary', 'subagent']
ToolFormat = Literal['bash', 'json', 'both']
TodoMode = Literal['strict', 'lazy', 'none']


class ModelParameters(BaseModel):
    model_name: str
    temperature: float | None = None


class AgentHeader(BaseModel):
    agent_id: str
    name: str
    description: str | None = None
    mode: AgentMode | None = Field(
        default=None,
        description=(
            "Invocation mode for THIS reference. On the agent's own header"
            " it can mirror AgentVariant.agent_mode; on subagent references"
            " it picks 'subagent' (Task tool) vs 'primary' (opencode_manager"
            " via bash). None defaults to 'subagent' at render time."
        ),
    )


class ToolPermissions(BaseModel):
    """Per-agent boolean toggles for built-in tools.

    Maps to OpenCode's `permission.read/write/edit/mcp` enforcement. These
    flow into both the generated permission YAML and the SECURITY POLICY
    block emitted in the agent's system prompt — keeping the two in sync.
    """

    read: bool = False
    write: bool = False
    edit: bool = False
    mcp: bool = False


class MCPServerDefinition(BaseModel):
    """A specific MCP server an agent is permitted to talk to.

    `name` keys the per-agent allowlist: OpenCode emits
    `permission.mcp.<name>: allow` (or `deny`) for each server the
    agent declares. `allowed_tools` optionally restricts which tools
    exposed by the server the agent may call — when empty, *every*
    tool from that server is allowed. `url` and `description` are
    propagated to the compiled frontmatter for human-readability and
    runtime discovery but the runtime itself only enforces the
    name + tool allowlist.
    """

    name: str = Field(description="MCP server identifier — keys the per-agent allowlist.")
    description: str | None = Field(
        default=None,
        description="Human-readable note about what this server exposes.",
    )
    url: str | None = Field(
        default=None,
        description="Optional MCP server endpoint URL (stdio servers may omit).",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tool names from this server the agent may call. Empty list"
            " = all tools allowed. Names not in this list become deny."
        ),
    )


class AgentWorkflowStep(BaseModel):
    header: str | None
    condition: str | None
    result: str | None
    rule: str | None
    tools_used: list[ToolDefinition]
    skills_used: list[SkillDefinition] = Field(default_factory=list)
    subagents_used: list[AgentHeader]


class AgentDefinition(BaseModel):
    header: AgentHeader
    _all_tools_permissions: list[ToolPermission] = PrivateAttr(default_factory=list)
    _all_agents_permissions: list[ToolPermission] = PrivateAttr(default_factory=list)

    skills: list[SkillDefinition] = Field(default_factory=list)
    subagents: list[AgentHeader] = Field(default_factory=list)
    extra_tools: list[ToolDefinition] = Field(default_factory=list)

    usage_explanation_long: str
    usage_explanation_short: str

    default_tool_format: ToolFormat = Field(
        default="bash",
        description=(
            "Preferred invocation path when a tool offers both bash and JSON"
            " schema. Bash is the runtime default; switch to 'json' for models"
            " that prefer structured tool calls; 'both' emits both contracts."
        ),
    )
    tool_format_overrides: dict[str, ToolFormat] = Field(
        default_factory=dict,
        description="Per-tool overrides keyed by ToolDefinitionHeader.name.",
    )
    model_class: str = Field(
        default="default",
        description=(
            "Symbolic class read by SplitProfile at compile time to pick"
            " a per-agent preset (e.g. 'fast' / 'analytical' / 'vision')."
            " Ignored unless the active VariantSpec is a SplitProfile."
        ),
    )
    workflow: list[WorkflowStepDefinition] = Field(
        default_factory=list,
        description=(
            "MANDATORY WORKFLOW for this agent — emitted as the body of the"
            " agent's system prompt when non-empty. See the workflow_prompt"
            " builder for rendering details."
        ),
    )
    todo_mode: TodoMode = Field(
        default="strict",
        description=(
            "strict = full STEP 0 task list + per-step mark-done;"
            " lazy = STEP 0 task list but no per-step marks;"
            " none = no todo tooling referenced at all."
        ),
    )
    workspace: str | None = Field(
        default=None,
        description=(
            "Sandbox directory pattern for workspace_io.py (e.g."
            " '.agent_workspace/{name}'). When set, the workflow prompt"
            " includes a STEP 0a workspace-init block. '{name}' is"
            " substituted with the postfixed agent name at render time."
        ),
    )
    system_prompt: str = Field(
        default="",
        description=(
            "Custom system prompt. When workflow is empty, this becomes the"
            " entire body of the agent's .md (falling back to"
            " usage_explanation_long if also empty). When workflow is set,"
            " system_prompt is prepended before the MANDATORY WORKFLOW block."
        ),
    )
    prompt_sections: list[dict] = Field(
        default_factory=list,
        description=(
            "Optional STRUCTURED form of system_prompt — an ordered list of"
            " named PromptSection objects (open_agent_compiler.improvement.prompt_sections)."
            " When non-empty, system_prompt is DERIVED from it, and the autoloop"
            " optimises each MUTABLE section in place (rewrite one section,"
            " keep the rest verbatim) instead of rewriting the whole prompt as"
            " one string — so a rich multi-section prompt can be improved"
            " without the optimiser silently dropping structure. Each section"
            " carries required (rewrite-but-never-remove) + mutable (frozen)"
            " flags. Empty list = classic flat system_prompt behaviour."
        ),
    )
    preamble: str = Field(
        default="",
        description=(
            "Content rendered between system_prompt and the MANDATORY"
            " WORKFLOW header. Workflow-only — ignored when workflow is empty."
        ),
    )
    postamble: str = Field(
        default="",
        description=(
            "Content rendered after the FINAL CHECKLIST. Workflow-only —"
            " ignored when workflow is empty."
        ),
    )
    inline_skills: bool = Field(
        default=False,
        description=(
            "Control how the workflow prompt presents this agent's skills."
            " False = name-reference style ('## Your Skills (use via bash)'"
            " with tool name list). True = full inline action docs"
            " ('## Available Bash Scripts' with bash command syntax per"
            " tool). Has no effect when workflow is empty."
        ),
    )
    tool_permissions: ToolPermissions | None = Field(
        default=None,
        description=(
            "Boolean toggles for built-in read/write/edit/mcp tools. None"
            " is equivalent to ToolPermissions() (everything off) — the"
            " security policy block uses these to phrase ALLOWED/FORBIDDEN."
        ),
    )
    mcp_servers: list["MCPServerDefinition"] = Field(
        default_factory=list,
        description=(
            "MCP servers this specific agent is allowed to call, with"
            " optional per-server tool allowlists. Each server name is"
            " emitted as permission.mcp.<name>=allow in the compiled"
            " frontmatter; tools the server exposes that are not in"
            " `allowed_tools` are emitted as deny so two agents can"
            " safely declare different server subsets in one compile."
            " Independent from the legacy boolean `tool_permissions.mcp`"
            " toggle — use `mcp_servers` for per-server granularity."
        ),
    )
    agent_tests: list[AgentTest] = Field(
        default_factory=list,
        description="End-to-end scenarios for this agent (Phase 5).",
    )
    capability_tests: list[CapabilityTest] = Field(
        default_factory=list,
        description="Pure-introspection assertions on the compiled artifact.",
    )
    tool_tests: list[ToolTest] = Field(
        default_factory=list,
        description=(
            "Agent-scoped tool tests — when this agent compiles under a"
            " given profile, these scenarios exercise its tools. Tool-level"
            " tests live on ToolDefinition.tool_tests."
        ),
    )

    def chosen_format(self, tool: ToolDefinition) -> ToolFormat:
        """Return the effective format for `tool` under this agent.

        Order: explicit override > agent default > falls back to whichever
        contract the tool actually carries (so a tool with only bash_tool
        always emits bash regardless of preference).
        """
        explicit = self.tool_format_overrides.get(tool.header.name)
        preferred: ToolFormat = explicit or self.default_tool_format
        has_bash = tool.bash_tool is not None
        has_json = tool.json_tool is not None
        if preferred == "both":
            return "both" if (has_bash and has_json) else (
                "bash" if has_bash else "json"
            )
        if preferred == "json" and not has_json:
            return "bash" if has_bash else "json"
        if preferred == "bash" and not has_bash:
            return "json" if has_json else "bash"
        return preferred


class AgentVariant(BaseModel):
    postfix: str = Field(default="", description="Unique postfix used for the agent variant")
    agent_mode: AgentMode = 'primary'
    agent_definition: AgentDefinition
    model_parameters: ModelParameters
    also_compile_as_primary: bool = Field(
        default=False,
        description=(
            "Carried over from the originating TemplateSlot. When True"
            " the compiler emits a second <name>-primary.md alongside"
            " the slot-derived file; see TemplateSlot for the rationale."
        ),
    )


class TemplateSlot(BaseModel):
    name: str
    default_agent_id: str
    also_compile_as_primary: bool = Field(
        default=False,
        description=(
            "When True, the compiler emits TWO files for this slot:"
            " <name>.md (with the slot-derived mode — subagent for any"
            " slot not named 'primary') AND <name>-primary.md (forced"
            " to mode=primary). The second file makes the same agent"
            " reachable directly via `opencode run --agent"
            " <name>-primary` OR via `opencode_manager.py run --agent"
            " <name>-primary` — useful both for direct invocation by"
            " other primaries and for autoresearch (subagents can't"
            " be invoked directly; the -primary twin can)."
        ),
    )


class TemplateTree(BaseModel):
    name: str
    description: str | None = None
    slots: list[TemplateSlot]


class CompilationConfig(BaseModel):
    name: str
    template_name: str
    postfix: str = ""
    slot_overrides: dict[str, str] = Field(default_factory=dict)
    strict_validation: bool = True
