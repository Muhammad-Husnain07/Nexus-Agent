"""SQLAlchemy model imports — all models register on Base.metadata."""
from nexus.db.models.enums import (
    ExecutionStatus, MemoryKind, MessageRole, SessionStatus, ToolRiskLevel,
)
from nexus.db.models.approval import ApprovalPolicy
from nexus.db.models.artifact import Artifact
from nexus.db.models.audit_log import AuditLog
from nexus.db.models.capability_version import CapabilityVersion
from nexus.db.models.compensation_log import CompensationLog
from nexus.db.models.dead_letter import DeadLetterExecution
from nexus.db.models.environment import Environment
from nexus.db.models.invocation_outcome import InvocationOutcome
from nexus.db.models.long_running_workflow import LongRunningWorkflow
from nexus.db.models.memory import Memory
from nexus.db.models.outbox import OutboxEvent
from nexus.db.models.registry import (
    CapabilityModel, EndpointModel, ProviderModel, RegistryVersionModel,
)
from nexus.db.models.project import Project
from nexus.db.models.session import Message, Session
from nexus.db.models.task import Task
from nexus.db.models.tool import Tool, ToolExecution
from nexus.db.models.user import User
from nexus.db.models.tool_version import ToolVersion
from nexus.db.models.workflow_definition import WorkflowDefinition, WorkflowInstance
from nexus.db.models.artifact_registry import ArtifactRecord
from nexus.db.models.workflow_template import WorkflowTemplate
# ExecutionEvent lives on the shared Base so Alembic autogenerate can see it
from nexus.execution.events import ExecutionEvent  # noqa: E402, F401

__all__ = [
    "ApprovalPolicy", "Artifact", "AuditLog", "CapabilityModel",
    "CapabilityVersion", "CompensationLog", "DeadLetterExecution",
    "EndpointModel", "Environment", "ExecutionEvent", "ExecutionStatus",
    "InvocationOutcome", "LongRunningWorkflow", "Memory", "MemoryKind",
    "Message", "MessageRole", "OutboxEvent", "Project", "ProviderModel",
    "RegistryVersionModel", "Session", "SessionStatus", "Task", "Tool",
    "ToolExecution", "ToolRiskLevel", "ToolVersion", "User",
    "WorkflowDefinition", "WorkflowInstance", "WorkflowTemplate",
]
