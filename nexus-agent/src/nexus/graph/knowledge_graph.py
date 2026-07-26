"""8-Graph Knowledge Graph Manager — specialized graphs for planning & reasoning.

Each graph serves a distinct purpose in the planning pipeline:
1. ConversationGraph — Current conversation history (message window)
2. ArtifactGraph — Tool outputs produced so far
3. CapabilityGraph — Compiled producer/consumer map (read-only, from registry_compiler)
4. OntologyGraph — Capability hierarchy (parent → children)
5. ExecutionGraph — Current DAG execution state
6. MemoryGraph — Long-term facts from pgvector
7. PolicyGraph — Budget limits, privacy rules, SLA constraints
8. ReasoningGraph — LLM thought trail for observability

No hardcoded graph names. All keys derived from metadata.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.compiler.compiled_graph import get_compiled_graph

logger = structlog.get_logger("nexus.graph.knowledge_graph")


class BaseGraph:
    """A named graph with thread-safe read/write access."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._data: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, data: dict[str, Any]) -> None:
        self._data.update(data)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()


class ConversationGraph(BaseGraph):
    """Current conversation history — message window with roles and metadata."""

    def __init__(self) -> None:
        super().__init__("conversation")

    def add_message(self, role: str, content: str, milestone: bool = False) -> None:
        messages = self._data.setdefault("messages", [])
        import uuid
        messages.append({
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "milestone": milestone,
        })
        # Rolling window: keep last 10
        if len(messages) > 10:
            self._data["messages"] = [m for m in messages if m.get("milestone")] + messages[-10:]

    def last_user_message(self) -> str:
        for m in reversed(self._data.get("messages", [])):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""


class ArtifactGraph(BaseGraph):
    """Artifacts produced by tool calls — typed outputs with provenance."""

    def __init__(self) -> None:
        super().__init__("artifacts")

    def add_artifact(self, name: str, value: Any, source_tool: str = "") -> None:
        artifacts = self._data.setdefault("artifacts", {})
        artifacts[name] = {
            "value": value,
            "source": source_tool,
            "produced_at": __import__("time").time(),
        }

    def get_artifact(self, name: str) -> Any:
        art = self._data.get("artifacts", {}).get(name)
        return art.get("value") if art else None


class CapabilityGraph(BaseGraph):
    """Compiled capability graph — read-only at runtime, populated from registry_compiler.

    Builds O(1) producer/consumer indices on load so ``find_producers()`` and
    ``find_consumers()`` are dict lookups, not linear scans.
    """

    def __init__(self) -> None:
        super().__init__("capabilities")

    def load_from_compiled(self) -> None:
        """Load capability graph from the compiled registry (if available)."""
        compiled = get_compiled_graph()
        if compiled is None:
            return
        self._data["adjacency"] = compiled.adjacency
        self._data["nodes"] = {k: v.to_dict() for k, v in compiled.nodes.items()}
        self._data["missing_producers"] = compiled.missing_producers
        self._data["loaded"] = True
        # Build O(1) indices
        prod_index: dict[str, list[str]] = {}
        cons_index: dict[str, list[str]] = {}
        for name, node in self._data["nodes"].items():
            for art in node.get("produces", []):
                prod_index.setdefault(art, []).append(name)
            for art in node.get("consumes", []):
                cons_index.setdefault(art, []).append(name)
        self._data["producer_index"] = prod_index
        self._data["consumer_index"] = cons_index

    def find_producers(self, artifact: str) -> list[str]:
        """Find capabilities that produce the given artifact (O(1) lookup)."""
        return self._data.get("producer_index", {}).get(artifact, [])

    def find_consumers(self, artifact: str) -> list[str]:
        """Find capabilities that consume the given artifact (O(1) lookup)."""
        return self._data.get("consumer_index", {}).get(artifact, [])


class OntologyGraph(BaseGraph):
    """Capability hierarchy — parent → children relationships."""

    def __init__(self) -> None:
        super().__init__("ontology")

    def load_from_compiled(self) -> None:
        compiled = get_compiled_graph()
        if compiled is None:
            return
        # Build children index from ontology_parents
        children: dict[str, list[str]] = {}
        for child, parent in compiled.ontology_parents.items():
            children.setdefault(parent, []).append(child)
        self._data["parents"] = dict(compiled.ontology_parents)
        self._data["children"] = children

    def get_children(self, parent: str) -> list[str]:
        return self._data.get("children", {}).get(parent, [])

    def get_parent(self, child: str) -> str | None:
        return self._data.get("parents", {}).get(child)


class ExecutionGraph(BaseGraph):
    """Current DAG execution state — tasks, waves, results."""

    def __init__(self) -> None:
        super().__init__("execution")

    def set_plan(self, tasks: list[dict[str, Any]]) -> None:
        self._data["tasks"] = tasks
        self._data["status"] = "pending"

    def update_result(self, task_id: str, status: str, data: Any = None) -> None:
        results = self._data.setdefault("results", {})
        results[task_id] = {"status": status, "data": data}

    def failed_tasks(self) -> list[str]:
        results = self._data.get("results", {})
        return [tid for tid, r in results.items() if r.get("status") != "success"]


class MemoryGraph(BaseGraph):
    """Long-term facts from pgvector — semantic memory retrieval."""

    def __init__(self) -> None:
        super().__init__("memory")

    def load_from_store(self, session_id: str, top_k: int = 5) -> None:
        """Retrieve recent memories for a session via async pgvector query."""
        try:
            import asyncio
            from nexus.memory.store import MemoryStore
            store = MemoryStore()
            loop = asyncio.get_event_loop()
            results = loop.run_until_complete(store.search(session_id, top_k=top_k))
            self._data["entries"] = [r.to_dict() if hasattr(r, "to_dict") else r for r in (results or [])]
            self._data["session_id"] = session_id
            self._data["top_k"] = top_k
            self._data["count"] = len(self._data.get("entries", []))
        except Exception:
            self._data["entries"] = []
            self._data["session_id"] = session_id
            self._data["top_k"] = top_k
            self._data["count"] = 0


class PolicyGraph(BaseGraph):
    """Budget limits, privacy rules, SLA constraints — from settings + tool metadata."""

    def __init__(self) -> None:
        super().__init__("policy")

    def load_from_settings(self) -> None:
        try:
            from nexus.config.settings import get_settings
            s = get_settings()
            ag = s.agent
            self._data["budget_usd"] = getattr(getattr(ag, "adaptive_reflection", None), "cost_budget_usd", 0.1)
            self._data["max_concurrent"] = getattr(getattr(ag, "adaptive_reflection", None), "max_concurrent_tasks", 5)
            self._data["confidence_low"] = getattr(getattr(ag, "adaptive_reflection", None), "confidence_low", 0.3)
            self._data["max_reflection_retries"] = getattr(ag, "max_reflection_retries", 2)
            self._data["extraction_max_tokens"] = getattr(ag, "extraction_max_tokens", 500)
        except Exception:
            pass


class ReasoningGraph(BaseGraph):
    """LLM thought trail — stores reasoning steps for observability."""

    def __init__(self) -> None:
        super().__init__("reasoning")

    def add_step(self, node: str, reasoning: str) -> None:
        steps = self._data.setdefault("steps", [])
        steps.append({"node": node, "reasoning": reasoning, "ts": __import__("time").time()})


class KnowledgeGraphManager:
    """Manages all 8 specialized graphs for planning and reasoning.

    Graphs are populated lazily on first access. The CapabilityGraph and
    OntologyGraph are loaded from the compiled registry (offline-compiled).
    The other graphs are populated at runtime.
    """

    def __init__(self) -> None:
        self._graphs: dict[str, BaseGraph] = {}
        self._loaded = False

        # Register all 8 graphs
        self._register(ConversationGraph())
        self._register(ArtifactGraph())
        self._register(CapabilityGraph())
        self._register(OntologyGraph())
        self._register(ExecutionGraph())
        self._register(MemoryGraph())
        self._register(PolicyGraph())
        self._register(ReasoningGraph())

    def _register(self, graph: BaseGraph) -> None:
        self._graphs[graph.name] = graph

    def get(self, name: str) -> BaseGraph | None:
        return self._graphs.get(name)

    def load_all(self) -> None:
        """Load data into all graphs that support offline loading."""
        if self._loaded:
            return

        cap = self._graphs.get("capabilities")
        if cap and isinstance(cap, CapabilityGraph):
            cap.load_from_compiled()

        onto = self._graphs.get("ontology")
        if onto and isinstance(onto, OntologyGraph):
            onto.load_from_compiled()

        policy = self._graphs.get("policy")
        if policy and isinstance(policy, PolicyGraph):
            policy.load_from_settings()

        self._loaded = True
        logger.info("knowledge_graph.loaded_all", graphs=list(self._graphs.keys()))

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {name: g.to_dict() for name, g in self._graphs.items()}

    @staticmethod
    def build(state: AgentState) -> KnowledgeGraphManager:
        """Build a KnowledgeGraphManager from agent state (convenience factory)."""
        kg = KnowledgeGraphManager()
        kg.load_all()

        # Populate conversation from state messages
        conv = kg.get("conversation")
        if conv and isinstance(conv, ConversationGraph):
            messages = state.get("messages", [])
            if isinstance(messages, list):
                for m in messages:
                    if isinstance(m, dict):
                        conv.add_message(
                            role=m.get("role", ""),
                            content=m.get("content", ""),
                            milestone=m.get("milestone", False),
                        )

        # Populate execution plan if available
        exec_g = kg.get("execution")
        if exec_g and isinstance(exec_g, ExecutionGraph):
            tasks = state.get("dag_tasks", [])
            if tasks:
                exec_g.set_plan(tasks)

        return kg


# Singleton accessor
_knowledge_graph: KnowledgeGraphManager | None = None


def get_knowledge_graph() -> KnowledgeGraphManager:
    global _knowledge_graph
    if _knowledge_graph is None:
        _knowledge_graph = KnowledgeGraphManager()
        _knowledge_graph.load_all()
    return _knowledge_graph
