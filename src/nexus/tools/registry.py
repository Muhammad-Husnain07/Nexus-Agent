"""ToolRegistry — CRUD, semantic search, and embedding generation for tools."""

from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config.settings import get_settings
from nexus.db.models.tool import Tool
from nexus.db.models.tool_version import ToolVersion
from nexus.llm.client import LLMClient
from nexus.tools.schemas import (
    ToolCreate,
    ToolList,
    ToolRead,
    ToolSearchResult,
    ToolUpdate,
)

logger = structlog.get_logger("nexus.tools.registry")

EMBEDDING_MODEL: str = get_settings().llm.embedding_model


def _tool_to_read(tool: Tool) -> ToolRead:
    return ToolRead(
        id=tool.id,
        tenant_id=tool.tenant_id,
        name=tool.name,
        description=tool.description or "",
        purpose=tool.purpose or "",
        endpoint_url=tool.endpoint_url or "",
        http_method=tool.http_method or "GET",
        auth_type=tool.auth_type or "none",
        auth_ref=tool.auth_ref or "",
        input_schema=tool.input_schema or {},
        output_schema=tool.output_schema or {},
        validation_rules=tool.validation_rules or {},
        examples=tool.examples or [],
        tags=tool.tags or [],
        category=tool.category or "general",
        requires_approval=tool.requires_approval or False,
        risk_level=tool.risk_level or "low",
        enabled=tool.enabled if tool.enabled is not None else True,
        version=tool.version or 1,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
        embedding=tool.embedding,
    )


def _embedding_text(tool: ToolCreate | Tool) -> str:
    name = tool.name if isinstance(tool, Tool) else tool.name
    desc = tool.description if isinstance(tool, Tool) else tool.description
    purp = tool.purpose if isinstance(tool, Tool) else tool.purpose
    tags_list = tool.tags if isinstance(tool, Tool) else tool.tags
    tag_str = ",".join(sorted(tags_list)) if tags_list else ""
    return f"{name}: {desc}. {purp}. tags: {tag_str}"


class ToolRegistry:
    """Service for managing tool definitions with semantic search.

    All operations are scoped to a tenant. Embeddings are generated via
    ``LLMClient.embed`` using ``text-embedding-3-small``.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def register(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        data: ToolCreate,
    ) -> ToolRead:
        """Register a new tool, generate its embedding, and return it."""
        tool = Tool(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            purpose=data.purpose,
            endpoint_url=data.endpoint_url,
            http_method=data.http_method,
            auth_type=data.auth_type,
            auth_ref=data.auth_ref,
            input_schema=data.input_schema,
            output_schema=data.output_schema,
            validation_rules=data.validation_rules,
            examples=[e.model_dump() for e in data.examples],
            tags=data.tags,
            category=data.category,
            requires_approval=data.requires_approval,
            risk_level=data.risk_level,
            enabled=data.enabled,
            version=1,
        )
        session.add(tool)
        await session.flush()

        tool.embedding = await self._generate_embedding(_embedding_text(tool))
        await session.flush()

        logger.info("tool.registered", tool_id=str(tool.id), name=tool.name)
        return _tool_to_read(tool)

    async def update(  # noqa: PLR0913
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tool_id: uuid.UUID,
        data: ToolUpdate,
        changed_by: str | None = None,
        change_comment: str | None = None,
    ) -> ToolRead | None:
        """Update a tool, snapshot to ToolVersion, regenerate embedding if needed."""
        tool = await self._get_model(session, tenant_id, tool_id)
        if tool is None:
            return None

        old_text = _embedding_text(tool)
        needs_reembed = False

        update_dict = data.model_dump(exclude_unset=True)

        for field, raw_val in update_dict.items():
            val = raw_val
            if field == "examples" and val is not None:
                val = [e.model_dump() for e in val]
            setattr(tool, field, val)
            if field in ("name", "description", "purpose", "tags"):
                needs_reembed = True

        if update_dict:
            snapshot = _tool_to_read(tool).model_dump(mode="json")
            version = ToolVersion(
                tenant_id=tenant_id,
                tool_id=tool.id,
                version=tool.version,
                snapshot=snapshot,
                changed_by=changed_by,
                change_comment=change_comment,
            )
            session.add(version)
            tool.version = (tool.version or 1) + 1

        if needs_reembed:
            new_text = _embedding_text(tool)
            if new_text != old_text:
                tool.embedding = await self._generate_embedding(new_text)

        await session.flush()
        logger.info("tool.updated", tool_id=str(tool.id), version=tool.version)
        return _tool_to_read(tool)

    async def deregister(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tool_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a tool by setting ``enabled=False``. Returns True if found."""
        tool = await self._get_model(session, tenant_id, tool_id)
        if tool is None:
            return False
        tool.enabled = False
        await session.flush()
        logger.info("tool.deregistered", tool_id=str(tool.id))
        return True

    async def get(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tool_id: uuid.UUID,
    ) -> ToolRead | None:
        """Get a single tool by id (any enabled state)."""
        tool = await self._get_model(session, tenant_id, tool_id)
        return _tool_to_read(tool) if tool else None

    async def list(  # noqa: PLR0913
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tags: list[str] | None = None,
        category: str | None = None,
        enabled: bool | None = True,
        page: int = 1,
        page_size: int = 20,
    ) -> ToolList:
        """List tools with optional filters and pagination."""
        query = select(Tool).where(Tool.tenant_id == tenant_id)

        if enabled is not None:
            query = query.where(Tool.enabled == enabled)
        if category:
            query = query.where(Tool.category == category)
        if tags:
            query = query.where(Tool.tags.overlap(tags))

        count_query = select(text("count(*)")).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(Tool.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        tools = await result.scalars().all()

        return ToolList(
            items=[_tool_to_read(t) for t in tools],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def search_semantic(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        k: int = 10,
    ) -> list[ToolSearchResult]:
        """Search tools by semantic similarity using pgvector cosine distance.

        The query string is embedded via ``LLMClient.embed``, then a
        ``<->`` (cosine distance) ORDER BY clause returns the closest matches.
        """
        query_vector = (await self._generate_embedding(query)) or []
        if not query_vector:
            return []

        vector_literal = json.dumps(query_vector)
        sql = text(
            "SELECT id, embedding <=> :query_vec AS distance "
            "FROM tool "
            "WHERE tenant_id = :tid AND enabled = true AND embedding IS NOT NULL "
            "ORDER BY distance "
            "LIMIT :k"
        )
        rows = await session.execute(
            sql,
            {"query_vec": vector_literal, "tid": tenant_id, "k": k},
        )

        tool_ids = []
        scores: dict[uuid.UUID, float] = {}
        async for row in rows:
            tid: uuid.UUID = row[0]
            distance: float = row[1]
            tool_ids.append(tid)
            scores[tid] = round(1.0 - distance, 4)

        if not tool_ids:
            return []

        tools_result = await session.execute(select(Tool).where(Tool.id.in_(tool_ids)))
        tools_map = {t.id: t for t in await tools_result.scalars().all()}

        return [
            ToolSearchResult(tool=_tool_to_read(tools_map[tid]), score=scores[tid])
            for tid in tool_ids
            if tid in tools_map
        ]

    async def _generate_embedding(self, text: str) -> list[float]:
        try:
            embeddings = await self._llm.embed(EMBEDDING_MODEL, [text])
            if embeddings:
                return embeddings[0]
        except Exception:
            logger.warning("embedding.failed", exc_info=True)
        return []

    @staticmethod
    async def _get_model(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tool_id: uuid.UUID,
    ) -> Tool | None:
        result = await session.execute(
            select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()
