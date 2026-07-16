"""Model router — picks the right model for each task type per tenant config."""

from __future__ import annotations

import enum
import uuid

from nexus.config.settings import LLMSettings, get_settings


class TaskType(str, enum.Enum):  # noqa: UP042
    """Type of task the LLM is being used for.

    Attributes:
        PLANNING: Complex multi-step reasoning, plan generation.
        TOOL_SELECTION: Choosing which tool to invoke next.
        SUMMARIZATION: Condensing conversation context.
        CHAT: General conversational response.
        EMBEDDING: Generating text embeddings.
    """

    PLANNING = "planning"
    TOOL_SELECTION = "tool_selection"
    SUMMARIZATION = "summarization"
    CHAT = "chat"
    EMBEDDING = "embedding"


class ModelRouter:
    """Maps task types to model identifiers per tenant configuration.

    Default mapping uses a tiered strategy:
    - PLANNING → strongest/expensive model
    - TOOL_SELECTION → fast/cheap model
    - SUMMARIZATION → cheap model with large context
    - CHAT → tenant default model
    - EMBEDDING → dedicated embedding model

    The mapping can be overridden by tenant-level settings in the future.
    """

    def __init__(self, llm_settings: LLMSettings | None = None) -> None:
        self._settings = llm_settings or get_settings().llm
        self._default_model = self._settings.default_model
        self._default_provider = self._settings.default_provider
        self._task_map = self._build_default_map()

    def _build_default_map(self) -> dict[TaskType, str]:
        default = self._default_model
        return {
            TaskType.PLANNING: default,
            TaskType.TOOL_SELECTION: "gpt-4o-mini",
            TaskType.SUMMARIZATION: "gpt-4o-mini",
            TaskType.CHAT: default,
            TaskType.EMBEDDING: "text-embedding-3-small",
        }

    def get_model(self, task: TaskType, tenant_id: uuid.UUID | None = None) -> str:
        """Return the model identifier for a given task type.

        Args:
            task: The type of task to route.
            tenant_id: Optional tenant ID for per-tenant model overrides.

        Returns:
            A model identifier string suitable for LiteLLM.
        """
        return self._task_map.get(task, self._default_model)

    def register_override(
        self,
        task: TaskType,
        model: str,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        """Register a task-to-model override.

        Args:
            task: Task type to override.
            model: Model identifier to route to.
            tenant_id: Optional tenant ID for scoped override.
        """
        self._task_map[task] = model
