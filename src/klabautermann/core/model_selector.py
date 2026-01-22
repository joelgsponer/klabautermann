"""
Multi-model orchestration for Klabautermann.

Dynamically selects the appropriate Claude model based on task complexity,
optimizing for cost while maintaining quality.

Reference: specs/architecture/AGENTS.md Section 3
Reference: Issue #3 [AGT-P-002]
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.metrics import record_llm_call, record_llm_latency, record_llm_tokens


if TYPE_CHECKING:
    import anthropic


class ModelTier(str, Enum):
    """Available Claude model tiers.

    Models are organized by capability and cost:
    - HAIKU: Fast, cheap, good for simple tasks
    - SONNET: Balanced, good for complex reasoning
    - OPUS: Most capable, highest cost, for critical tasks
    """

    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class TaskComplexity(str, Enum):
    """Task complexity levels for model selection.

    Complexity determines which model tier to use:
    - SIMPLE: Classification, extraction, simple queries -> Haiku
    - MODERATE: Reasoning, synthesis, planning -> Sonnet
    - COMPLEX: Multi-step reasoning, critical decisions -> Opus
    """

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class TaskPurpose(str, Enum):
    """Purpose of the LLM call for metrics and selection.

    These map to specific model tiers by default:
    - CLASSIFICATION: Intent detection -> Haiku
    - EXTRACTION: Entity extraction -> Haiku
    - SEARCH_PLANNING: Query construction -> Haiku
    - REASONING: Complex reasoning -> Sonnet
    - SYNTHESIS: Response generation -> Sonnet/Opus
    - PLANNING: Task planning -> Opus
    - ACTION: Tool/MCP execution -> Sonnet
    """

    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    SEARCH_PLANNING = "search_planning"
    REASONING = "reasoning"
    SYNTHESIS = "synthesis"
    PLANNING = "planning"
    ACTION = "action"


# Default model IDs for each tier
DEFAULT_MODELS: dict[ModelTier, str] = {
    ModelTier.HAIKU: "claude-3-5-haiku-20241022",
    ModelTier.SONNET: "claude-sonnet-4-20250514",
    ModelTier.OPUS: "claude-opus-4-5-20251101",
}

# Map task purpose to default model tier
PURPOSE_TO_TIER: dict[TaskPurpose, ModelTier] = {
    TaskPurpose.CLASSIFICATION: ModelTier.HAIKU,
    TaskPurpose.EXTRACTION: ModelTier.HAIKU,
    TaskPurpose.SEARCH_PLANNING: ModelTier.HAIKU,
    TaskPurpose.REASONING: ModelTier.SONNET,
    TaskPurpose.SYNTHESIS: ModelTier.SONNET,
    TaskPurpose.PLANNING: ModelTier.OPUS,
    TaskPurpose.ACTION: ModelTier.SONNET,
}

# Map complexity to default model tier
COMPLEXITY_TO_TIER: dict[TaskComplexity, ModelTier] = {
    TaskComplexity.SIMPLE: ModelTier.HAIKU,
    TaskComplexity.MODERATE: ModelTier.SONNET,
    TaskComplexity.COMPLEX: ModelTier.OPUS,
}


@dataclass
class ModelSelectionConfig:
    """Configuration for model selection.

    Allows per-agent and per-purpose model overrides.
    """

    # Default models by tier (can be overridden)
    models: dict[ModelTier, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))

    # Per-purpose overrides (e.g., use Sonnet for extraction in prod)
    purpose_overrides: dict[TaskPurpose, ModelTier] = field(default_factory=dict)

    # Per-agent overrides (e.g., researcher always uses Opus)
    agent_overrides: dict[str, ModelTier] = field(default_factory=dict)

    # Fallback model if primary fails
    fallback_tier: ModelTier = ModelTier.SONNET

    # Enable metrics recording
    record_metrics: bool = True

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> ModelSelectionConfig:
        """Create ModelSelectionConfig from agent config dict.

        Args:
            config: Agent configuration dictionary.

        Returns:
            ModelSelectionConfig instance.
        """
        if not config:
            return cls()

        model_config = config.get("model_selection", {})

        # Parse model overrides
        models = dict(DEFAULT_MODELS)
        if "models" in model_config:
            for tier_name, model_id in model_config["models"].items():
                try:
                    tier = ModelTier(tier_name.lower())
                    models[tier] = model_id
                except ValueError:
                    logger.warning(f"[SWELL] Unknown model tier: {tier_name}")

        # Parse purpose overrides
        purpose_overrides: dict[TaskPurpose, ModelTier] = {}
        if "purpose_overrides" in model_config:
            for purpose_name, tier_name in model_config["purpose_overrides"].items():
                try:
                    purpose = TaskPurpose(purpose_name.lower())
                    tier = ModelTier(tier_name.lower())
                    purpose_overrides[purpose] = tier
                except ValueError:
                    logger.warning(f"[SWELL] Unknown purpose or tier: {purpose_name}={tier_name}")

        # Parse agent overrides
        agent_overrides: dict[str, ModelTier] = {}
        if "agent_overrides" in model_config:
            for agent_name, tier_name in model_config["agent_overrides"].items():
                try:
                    tier = ModelTier(tier_name.lower())
                    agent_overrides[agent_name] = tier
                except ValueError:
                    logger.warning(f"[SWELL] Unknown tier for agent {agent_name}: {tier_name}")

        # Parse fallback
        fallback_tier = ModelTier.SONNET
        if "fallback_tier" in model_config:
            try:
                fallback_tier = ModelTier(model_config["fallback_tier"].lower())
            except ValueError:
                logger.warning(f"[SWELL] Unknown fallback tier: {model_config['fallback_tier']}")

        return cls(
            models=models,
            purpose_overrides=purpose_overrides,
            agent_overrides=agent_overrides,
            fallback_tier=fallback_tier,
            record_metrics=model_config.get("record_metrics", True),
        )


@dataclass
class ModelCallResult:
    """Result of a model call with metadata."""

    response: str
    model_id: str
    model_tier: ModelTier
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    used_fallback: bool = False


class ModelSelector:
    """Selects and calls the appropriate Claude model based on task complexity.

    This class provides a unified interface for model selection across all agents,
    implementing the multi-model orchestration pattern from Issue #3.

    Example usage:
        selector = ModelSelector(anthropic_client, config)

        # Select model by purpose
        result = await selector.call(
            prompt="Classify this intent: ...",
            purpose=TaskPurpose.CLASSIFICATION,
            trace_id=trace_id,
        )

        # Select model by complexity
        result = await selector.call(
            prompt="Plan the following tasks...",
            complexity=TaskComplexity.COMPLEX,
            trace_id=trace_id,
        )

        # Agent-specific override
        result = await selector.call(
            prompt="Search for...",
            purpose=TaskPurpose.SEARCH_PLANNING,
            agent_name="researcher",
            trace_id=trace_id,
        )
    """

    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        config: ModelSelectionConfig | None = None,
    ) -> None:
        """Initialize the model selector.

        Args:
            anthropic_client: Anthropic client for API calls.
            config: Model selection configuration.
        """
        self.client = anthropic_client
        self.config = config or ModelSelectionConfig()

    def select_model(
        self,
        purpose: TaskPurpose | None = None,
        complexity: TaskComplexity | None = None,
        agent_name: str | None = None,
    ) -> tuple[str, ModelTier]:
        """Select the appropriate model based on purpose, complexity, and agent.

        Priority order:
        1. Agent override (if configured)
        2. Purpose override (if configured)
        3. Complexity (if provided)
        4. Purpose default (if provided)
        5. Fallback to SONNET

        Args:
            purpose: Purpose of the LLM call.
            complexity: Complexity level of the task.
            agent_name: Name of the calling agent.

        Returns:
            Tuple of (model_id, model_tier).
        """
        tier: ModelTier | None = None

        # 1. Check agent override
        if agent_name and agent_name in self.config.agent_overrides:
            tier = self.config.agent_overrides[agent_name]
            logger.debug(
                f"[WHISPER] Using agent override for {agent_name}: {tier.value}",
                extra={"agent_name": agent_name, "model_tier": tier.value},
            )

        # 2. Check purpose override
        elif purpose and purpose in self.config.purpose_overrides:
            tier = self.config.purpose_overrides[purpose]
            logger.debug(
                f"[WHISPER] Using purpose override for {purpose.value}: {tier.value}",
                extra={"purpose": purpose.value, "model_tier": tier.value},
            )

        # 3. Use complexity if provided
        elif complexity:
            tier = COMPLEXITY_TO_TIER[complexity]
            logger.debug(
                f"[WHISPER] Selected model by complexity {complexity.value}: {tier.value}",
                extra={"complexity": complexity.value, "model_tier": tier.value},
            )

        # 4. Use purpose default
        elif purpose:
            tier = PURPOSE_TO_TIER[purpose]
            logger.debug(
                f"[WHISPER] Selected model by purpose {purpose.value}: {tier.value}",
                extra={"purpose": purpose.value, "model_tier": tier.value},
            )

        # 5. Fallback
        if tier is None:
            tier = self.config.fallback_tier
            logger.debug(
                f"[WHISPER] Using fallback model tier: {tier.value}",
                extra={"model_tier": tier.value},
            )

        model_id = self.config.models[tier]
        return model_id, tier

    async def call(
        self,
        prompt: str,
        purpose: TaskPurpose | None = None,
        complexity: TaskComplexity | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> ModelCallResult:
        """Call the appropriate model based on task characteristics.

        Selects model, makes the API call, records metrics, and handles fallback.

        Args:
            prompt: The prompt to send to the model.
            purpose: Purpose of the LLM call (for model selection and metrics).
            complexity: Complexity level of the task.
            agent_name: Name of the calling agent.
            trace_id: Request trace ID for logging.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            system_prompt: Optional system prompt.

        Returns:
            ModelCallResult with response and metadata.
        """
        model_id, tier = self.select_model(purpose, complexity, agent_name)

        logger.info(
            f"[WHISPER] Calling {tier.value} model ({model_id})",
            extra={
                "trace_id": trace_id,
                "model": model_id,
                "model_tier": tier.value,
                "purpose": purpose.value if purpose else None,
                "agent_name": agent_name,
            },
        )

        start_time = time.perf_counter()
        used_fallback = False

        try:
            response = await self._make_call(
                model_id=model_id,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
        except Exception as e:
            # Try fallback model
            fallback_id = self.config.models[self.config.fallback_tier]
            if fallback_id != model_id:
                logger.warning(
                    f"[SWELL] Primary model {model_id} failed, trying fallback {fallback_id}: {e}",
                    extra={"trace_id": trace_id, "error": str(e)},
                )
                response = await self._make_call(
                    model_id=fallback_id,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
                model_id = fallback_id
                tier = self.config.fallback_tier
                used_fallback = True
            else:
                raise

        latency = time.perf_counter() - start_time

        # Extract response text and token counts
        response_text = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Record metrics
        if self.config.record_metrics:
            purpose_str = purpose.value if purpose else "unknown"
            record_llm_call(model=tier.value, purpose=purpose_str)
            record_llm_tokens(
                model=tier.value, input_tokens=input_tokens, output_tokens=output_tokens
            )
            record_llm_latency(model=tier.value, latency_seconds=latency)

        logger.debug(
            f"[BEACON] Model call completed in {latency:.2f}s",
            extra={
                "trace_id": trace_id,
                "model": model_id,
                "model_tier": tier.value,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_seconds": latency,
                "used_fallback": used_fallback,
            },
        )

        return ModelCallResult(
            response=response_text,
            model_id=model_id,
            model_tier=tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_seconds=latency,
            used_fallback=used_fallback,
        )

    async def _make_call(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> Any:
        """Make the actual API call.

        Args:
            model_id: Model ID to use.
            prompt: User prompt.
            max_tokens: Max response tokens.
            temperature: Sampling temperature.
            system_prompt: Optional system prompt.

        Returns:
            API response object.
        """
        import asyncio

        messages = [{"role": "user", "content": prompt}]

        # Run synchronous Anthropic call in executor
        def _sync_call() -> Any:
            kwargs: dict[str, Any] = {
                "model": model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            return self.client.messages.create(**kwargs)

        return await asyncio.get_event_loop().run_in_executor(None, _sync_call)

    def get_model_for_purpose(self, purpose: TaskPurpose) -> str:
        """Get the model ID for a specific purpose.

        Convenience method for agents that need to know the model
        without making a call.

        Args:
            purpose: Purpose of the LLM call.

        Returns:
            Model ID string.
        """
        model_id, _ = self.select_model(purpose=purpose)
        return model_id

    def get_model_for_complexity(self, complexity: TaskComplexity) -> str:
        """Get the model ID for a specific complexity level.

        Args:
            complexity: Complexity level.

        Returns:
            Model ID string.
        """
        model_id, _ = self.select_model(complexity=complexity)
        return model_id


def get_model_for_agent(agent_name: str, config: dict[str, Any] | None = None) -> str:
    """Get the recommended model for a specific agent.

    This is a convenience function for agents that don't use the full
    ModelSelector but still want to respect the model selection config.

    Args:
        agent_name: Name of the agent.
        config: Agent configuration.

    Returns:
        Model ID string.
    """
    selection_config = ModelSelectionConfig.from_config(config)

    # Check agent override first
    if agent_name in selection_config.agent_overrides:
        tier = selection_config.agent_overrides[agent_name]
        return selection_config.models[tier]

    # Default mapping based on agent name
    agent_tiers: dict[str, ModelTier] = {
        "orchestrator": ModelTier.SONNET,
        "ingestor": ModelTier.HAIKU,
        "researcher": ModelTier.HAIKU,  # Per spec: "Query construction"
        "executor": ModelTier.SONNET,
        "archivist": ModelTier.HAIKU,
        "scribe": ModelTier.HAIKU,
        "bard": ModelTier.HAIKU,
        "officer": ModelTier.HAIKU,
    }

    tier = agent_tiers.get(agent_name, selection_config.fallback_tier)
    return selection_config.models[tier]


__all__ = [
    "COMPLEXITY_TO_TIER",
    "DEFAULT_MODELS",
    "PURPOSE_TO_TIER",
    "ModelCallResult",
    "ModelSelectionConfig",
    "ModelSelector",
    "ModelTier",
    "TaskComplexity",
    "TaskPurpose",
    "get_model_for_agent",
]
