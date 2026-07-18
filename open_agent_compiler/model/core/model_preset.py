"""ModelPreset — richer-than-ModelParameters per-agent model descriptor.

ModelParameters (model_name + temperature) was the v0.1 minimum. Anything
beyond that (provider routing, context window, reasoning/thinking config,
top-p, top-k, etc.) had to live somewhere outside the registry. ModelPreset
collapses that into one explicit unit so:

- The registry can register the same logical agent under multiple presets
  (e.g. {fast: glm-4.5-air, deep: claude-sonnet-4-5}) to enable per-variant
  compilation in Phase 2.1.
- The dialect writer can emit provider config blocks from one source of
  truth instead of guessing from a model name.
- Tests can pin presets explicitly without leaking provider details into
  every test file.

ModelPreset stays additive: registering with a ModelParameters still works,
and converting a preset to ModelParameters is mechanical so the existing
compiler path (which reads `model_parameters.model_name`) keeps working.
"""

from __future__ import annotations


from pydantic import BaseModel, ConfigDict, Field

from open_agent_compiler.model.core.agent_model import ModelParameters

ReasoningField = bool | str  # True/False, or a custom field name


class ModelLimits(BaseModel):
    model_config = ConfigDict(frozen=True)
    context: int | None = None
    output: int | None = None


class SamplingDefaults(BaseModel):
    model_config = ConfigDict(frozen=True)
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None


class ModelPreset(BaseModel):
    """A reusable, named model configuration.

    The `name` is the registry key — the same logical agent registered
    under preset names "fast" and "deep" produces two agent_ids that
    differ only by which preset they bound at registration time.

    `provider` and `model_id` are what the dialect actually emits; the
    registry uses them only for id generation. Other fields tune sampling
    and reasoning behavior. Adapter-specific extras (base_url, api_key
    env-var) live in `provider_options` as opaque key-value pairs so new
    providers do not need a schema change to be wired up.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    provider: str
    model_id: str
    sampling: SamplingDefaults = Field(default_factory=SamplingDefaults)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    reasoning: bool = False
    interleaved: ReasoningField | None = None
    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    provider_options: dict[str, str] = Field(default_factory=dict)
    description: str | None = None

    @property
    def qualified_model_name(self) -> str:
        """Provider-qualified model string (e.g. 'zai-coding-plan/glm-5.1').

        OpenCode reads the agent's frontmatter `model` field and expects
        the qualified form. When `model_id` already contains a '/'
        (caller pre-qualified) we trust it and return as-is. When provider
        is empty we return just model_id (legacy use cases).
        """
        if not self.provider:
            return self.model_id
        if "/" in self.model_id:
            return self.model_id
        return f"{self.provider}/{self.model_id}"

    def to_model_parameters(self) -> ModelParameters:
        """Project to the v0.1 ModelParameters shape for legacy compiler paths."""
        return ModelParameters(
            model_name=self.qualified_model_name,
            temperature=self.sampling.temperature,
        )
