"""ToolRegistry — CRUD, semantic search, and embedding generation for tools."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config.settings import get_settings
from nexus.db.models.tool import Tool
from nexus.db.models.tool_version import ToolVersion
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.rate_limiter import RateLimitError, TokenBucketRateLimiter
from nexus.tools.result import ToolResult
from nexus.tools.sandbox import check_allowed_host
from nexus.tools.schemas import (
    ToolCreate,
    ToolList,
    ToolRead,
    ToolSearchResult,
    ToolUpdate,
)

logger = structlog.get_logger("nexus.tools.registry")

EMBEDDING_MODEL: str = get_settings().llm.embedding_model

# Policy defaults for the contract block — resolved from settings once, so
# the execution_policy block is self-contained per capability.
_TOOL_DEFAULT_TIMEOUT_S: float = float(
    getattr(get_settings().tools, "execution_timeout_s", 20.0) or 20.0
)
_TOOL_DEFAULT_RETRIES: int = int(
    getattr(get_settings().tools, "max_retries", 0) or 0
)

# Mutation marker for the plan cache fingerprint — bumped whenever a tool is
# registered/updated/deregistered so cached plans never go stale (the
# compiled graph's checksum doesn't change on API tool changes). Persisted in
# Redis so the marker survives restarts: an in-memory-only marker resets on
# boot and stale plans cached by a previous process stay valid.
_TOOL_REGISTRY_MARKER: str = ""
_MARKER_REDIS_KEY: str = "nexus:tool_registry_marker"


def get_tool_registry_marker() -> str:
    """Return the current tool-registry mutation marker (restart-safe).

    On a cold start the in-memory marker is empty; the last-known value is
    restored from Redis so the cache fingerprint remains stable across
    restarts and never re-validates plans from an older tool set.
    """
    global _TOOL_REGISTRY_MARKER  # noqa: PLW0603
    if _TOOL_REGISTRY_MARKER:
        return _TOOL_REGISTRY_MARKER
    try:
        from nexus.config.settings import get_settings

        import redis as _blocking_redis

        settings = get_settings()
        client = _blocking_redis.Redis.from_url(
            settings.redis.url,
            db=settings.redis.db,
            socket_timeout=0.5,
            decode_responses=True,
        )
        try:
            persisted = client.get(_MARKER_REDIS_KEY)
        finally:
            client.close()
        if persisted:
            _TOOL_REGISTRY_MARKER = str(persisted)
    except Exception:
        pass
    return _TOOL_REGISTRY_MARKER


def _bump_tool_registry_marker() -> None:
    """Bump the marker (idempotent per change window) and persist it.

    The Redis write is a best-effort blocking SET — tool mutations are rare
    and the short socket timeout bounds any impact.
    """
    global _TOOL_REGISTRY_MARKER  # noqa: PLW0603
    import time as _t

    _TOOL_REGISTRY_MARKER = f"tools:{_t.time():.0f}"
    try:
        from nexus.config.settings import get_settings

        import redis as _blocking_redis

        settings = get_settings()
        client = _blocking_redis.Redis.from_url(
            settings.redis.url,
            db=settings.redis.db,
            socket_timeout=0.5,
            decode_responses=True,
        )
        try:
            client.set(_MARKER_REDIS_KEY, _TOOL_REGISTRY_MARKER)
        finally:
            client.close()
    except Exception:
        pass


async def _refresh_resolution_indexes() -> None:
    """Rebuild GlobalContext + retriever indexes after registry changes.

    Tool registration/update/deregister changes the alias/domain/keyword
    maps that retrieval and resolution read — the in-memory indexes must
    stay in sync or newly registered tools are invisible to the runtime.
    Best-effort: failures only warn (the next startup rebuilds cleanly).
    """
    try:
        from nexus.compiler.compiled_graph import load_compiled_graph_async
        from nexus.context.global_context import GlobalContext, get_global_context, set_global_context
        from nexus.db.base import async_session as _refresh_db
        from nexus.capabilities.retrieval import get_capability_retriever, reset_capability_retriever

        compiled = await load_compiled_graph_async()
        if compiled:
            async with _refresh_db() as _db:
                ctx = await GlobalContext.build(compiled, tool_session=_db)
            set_global_context(ctx)
            _bump_tool_registry_marker()
            # Retriever corpus is built from GlobalContext on first use —
            # reset it so the next retrieve() rebuilds with fresh metadata.
            reset_capability_retriever()
            _ = get_global_context()
            logger.info(
                "registry.indexes_refreshed",
                capabilities=len(ctx.capability_providers),
                aliases=len(ctx.alias_index),
                domains=len(ctx.domain_index),
            )
    except Exception as exc:
        logger.warning("registry.indexes_refresh_failed", error=str(exc)[:200])


def _tool_to_read(tool: Tool) -> ToolRead:
    return ToolRead(
        id=tool.id,
        name=tool.name,
        description=tool.description or "",
        purpose=tool.purpose or "",
        tool_type=getattr(tool, "tool_type", "http_api"),
        endpoint_url=tool.endpoint_url or "",
        mcp_server_url=getattr(tool, "mcp_server_url", ""),
        http_method=tool.http_method or "GET",
        auth_type=tool.auth_type or "none",
        auth_ref=tool.auth_ref or "",
        input_schema=tool.input_schema or {},
        output_schema=tool.output_schema or {},
        validation_rules=tool.validation_rules or {},
        examples=tool.examples or [],
        tags=tool.tags or [],
        keywords=tool.keywords or [],
        aliases=tool.aliases or [],
        category=tool.category or "general",
        risk_level=tool.risk_level or "low",
        requires_approval=_requires_approval(tool),
        compensating_operation=getattr(tool, "compensating_operation", None),
        enabled=tool.enabled if tool.enabled is not None else True,
        tenant_public=bool(getattr(tool, "tenant_public", False)),
        idempotent=bool(getattr(tool, "idempotent", False)),
        capabilities=tool.capabilities or [],
        produces=tool.produces or [],
        consumes=tool.consumes or [],
        related=tool.related or [],
        cacheable=bool(getattr(tool, "cacheable", True)),
        version=tool.version or 1,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
        embedding=tool.embedding,
    )


def _requires_approval(tool: Any) -> bool:
    """Derive the approval requirement from tool metadata + settings.

    Uses the same settings-driven threshold as ``approval_gate.requires_approval``
    so the read path and the gate never diverge.
    """
    if getattr(tool, "requires_approval", False) is True:
        return True
    try:
        from nexus.config.settings import get_settings as _reg_settings
        settings = _reg_settings()
        risk_order = settings.agent.risk_order
        min_risk = settings.tools.approval_min_risk
        risk_level = getattr(tool, "risk_level", "low") or "low"
        return risk_order.get(risk_level, 0) >= risk_order.get(min_risk, 10_000)
    except Exception:
        return False


def _embedding_text(tool: ToolCreate | Tool) -> str:
    name = tool.name if isinstance(tool, Tool) else tool.name
    desc = tool.description if isinstance(tool, Tool) else tool.description
    purp = tool.purpose if isinstance(tool, Tool) else tool.purpose
    tags_list = tool.tags if isinstance(tool, Tool) else tool.tags
    tag_str = ",".join(sorted(tags_list)) if tags_list else ""
    return f"{name}: {desc}. {purp}. tags: {tag_str}"


def _coerce_examples(values: list[Any]) -> list[dict[str, Any]]:
    """Normalize example entries to plain dicts for JSONB storage.

    ``ToolUpdate.model_dump`` already serializes ``ToolExample`` models to
    dicts, and API clients may pass raw dicts directly — so entries can be
    either. ``.model_dump()`` must never be called on the output of
    ``model_dump()``.
    """
    return [v.model_dump() if hasattr(v, "model_dump") else v for v in values]


def _build_tool_contract(tool: Any) -> dict[str, Any]:
    """Build the capability contract dict from a tool definition.

    Fully metadata-driven — every field comes from the tool. The tool's
    validation rules are surfaced as ``business_rules`` so the
    ValidatorNode's Tier-3 check (which reads ``capability.contract.
    business_rules``) enforces exactly what the registration form declares.
    """
    return {
        "idempotent": getattr(tool, "idempotent", False),
        "risk_level": getattr(tool, "risk_level", None) or "low",
        "requires_approval": getattr(tool, "requires_approval", False),
        "cacheable": bool(getattr(tool, "cacheable", True)),
        "capabilities": list(getattr(tool, "capabilities", None) or []),
        "related": list(getattr(tool, "related", None) or []),
        "business_rules": getattr(tool, "validation_rules", None) or {},
        # Unified execution policy (Phase 4) — readers prefer this block and
        # fall back to the legacy keys above (back-compat).
        "execution_policy": {
            "timeout_s": _TOOL_DEFAULT_TIMEOUT_S,
            "retries": _TOOL_DEFAULT_RETRIES,
            "parallel": True,
            "risk_level": getattr(tool, "risk_level", None) or "low",
            "requires_approval": getattr(tool, "requires_approval", False),
            "idempotent": getattr(tool, "idempotent", False),
            "cacheable": bool(getattr(tool, "cacheable", True)),
            "budget_usd": None,
            "permissions": [],
            "rollback": getattr(tool, "compensating_operation", None),
            "maintenance_windows": [],
        },
    }


class ToolRegistry:
    """Service for managing tool definitions with semantic search."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def register(
        self,
        session: AsyncSession,
        data: ToolCreate,
        skip_embedding: bool = False,
    ) -> ToolRead:
        """Register a new tool, generate its embedding, and return it."""
        self._validate_no_python_code(data)
        self._validate_json_schema(data.input_schema)
        from nexus.tools.keywords import extract_keywords
        auto_keywords = extract_keywords(
            name=data.name,
            purpose=data.purpose,
            tags=data.tags,
            aliases=data.aliases,
        )
        tool = Tool(
            name=data.name,
            description=data.description,
            purpose=data.purpose,
            tool_type=data.tool_type,
            endpoint_url=data.endpoint_url,
            mcp_server_url=data.mcp_server_url,
            http_method=data.http_method,
            auth_type=data.auth_type,
            auth_ref=data.auth_ref or "",
            input_schema=data.input_schema,
            output_schema=data.output_schema,
            validation_rules=data.validation_rules,
            examples=[e.model_dump() for e in data.examples],
            tags=data.tags,
            category=data.category,
            risk_level=data.risk_level,
            requires_approval=data.requires_approval,
            compensating_operation=data.compensating_operation,
            idempotent=data.idempotent,
            rate_limit_per_minute=data.rate_limit_per_minute,
            enabled=data.enabled,
            keywords=data.keywords or auto_keywords,
            aliases=data.aliases,
            capabilities=data.capabilities,
            produces=data.produces,
            consumes=data.consumes,
            related=data.related,
            cacheable=data.cacheable,
            version=1,
        )
        session.add(tool)
        await session.flush()

        # Sync into the capability registry (capability + provider + endpoint
        # rows) so the agent's resolver/executor can use this tool — the
        # runtime resolves capabilities via the registry, not the tool table.
        await self._sync_capability_registry(session, tool)

        if not skip_embedding:
            emb = await self._generate_embedding(_embedding_text(tool))
            if emb is not None:
                tool.embedding = emb
                await session.flush()

        await session.refresh(tool)

        # Capability version history — first snapshot for this capability.
        from nexus.db.models.capability_version import CapabilityVersion

        session.add(
            CapabilityVersion(
                capability_id=tool.id,
                version=1,
                snapshot=_tool_to_read(tool).model_dump(mode="json"),
                changed_by=None,
                change_comment="Initial registration",
                active=True,
            )
        )
        await session.flush()

        logger.info("tool.registered", tool_id=str(tool.id), name=tool.name)
        return _tool_to_read(tool)

    async def update(  # noqa: PLR0913
        self,
        session: AsyncSession,
        tool_id: uuid.UUID,
        data: ToolUpdate,
        changed_by: str | None = None,
        change_comment: str | None = None,
    ) -> ToolRead | None:
        """Update a tool, snapshot to ToolVersion, regenerate embedding if needed."""
        tool = await self._get_model(session, tool_id)
        if tool is None:
            return None

        # Run ORM attribute access + snapshot in a sync context to avoid
        # MissingGreenlet from ARRAY/JSONB column lazy loading
        update_dict = data.model_dump(exclude_unset=True)

        def _sync_update(t_obj: Tool) -> tuple[ToolRead, str]:
            old_txt = _embedding_text(t_obj)
            for field, raw_val in update_dict.items():
                # ``model_dump`` already serialized nested models (e.g.
                # ``ToolExample``) to plain dicts — never call ``.model_dump()``
                # on the result.
                val = raw_val
                if field == "examples" and val is not None:
                    val = _coerce_examples(val)
                setattr(t_obj, field, val)
            if any(f in update_dict for f in ("name", "purpose", "tags", "aliases")):
                from nexus.tools.keywords import extract_keywords
                t_obj.keywords = extract_keywords(
                    name=t_obj.name,
                    purpose=t_obj.purpose or "",
                    tags=t_obj.tags,
                    aliases=data.aliases,
                )
            return _tool_to_read(t_obj), old_txt

        updated_read, old_text = await session.run_sync(
            lambda sync_sess: _sync_update(tool)
        )

        needs_reembed = any(f in update_dict for f in ("name", "description", "purpose", "tags"))

        if update_dict:
            snapshot = updated_read.model_dump(mode="json")
            version = ToolVersion(
                tool_id=tool.id,
                version=tool.version,
                snapshot=snapshot,
                changed_by=changed_by,
                change_comment=change_comment,
            )
            session.add(version)
            # Capability version history — same snapshot, capability-scoped.
            from nexus.db.models.capability_version import CapabilityVersion

            session.add(
                CapabilityVersion(
                    capability_id=tool.id,
                    version=tool.version,
                    snapshot=snapshot,
                    changed_by=changed_by,
                    change_comment=change_comment,
                    active=True,
                )
            )
            tool.version = (tool.version or 1) + 1

        if needs_reembed:
            new_text = _embedding_text(tool)
            if new_text != old_text:
                tool.embedding = await self._generate_embedding(new_text)

        await session.flush()
        # Keep the capability registry in sync with the tool definition.
        await self._sync_capability_registry(session, tool)
        logger.info("tool.updated", tool_id=str(tool.id), version=tool.version)
        return updated_read

    async def deregister(
        self,
        session: AsyncSession,
        tool_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a tool by setting ``enabled=False``."""
        tool = await self._get_model(session, tool_id)
        if tool is None:
            return False
        tool.enabled = False
        await session.flush()
        # Disable the capability in the registry too — the agent must stop
        # resolving it.
        from nexus.db.models.registry import CapabilityModel

        await session.execute(
            CapabilityModel.__table__.update()
            .where(CapabilityModel.id == tool_id)
            .values(enabled=False)
        )
        logger.info("tool.deregistered", tool_id=str(tool.id))
        return True

    async def _sync_capability_registry(
        self,
        session: AsyncSession,
        tool: Tool,
    ) -> None:
        """Upsert capability/provider/endpoint rows for a tool.

        The agent's resolver/executor read the capability registry (not the
        tool table) — without this sync, tools registered via the API are
        invisible to the runtime. Fully metadata-driven: every field comes
        from the tool definition.
        """
        from nexus.db.models.registry import CapabilityModel, EndpointModel, ProviderModel

        capability = await session.get(CapabilityModel, tool.id)
        if capability is None:
            capability = CapabilityModel(
                id=tool.id,
                name=tool.name,
                logical_op_name=tool.name,
                description=tool.description or tool.purpose or "",
                tags=tool.tags or [],
                consumes=tool.consumes or [],
                produces=tool.produces or [],
                contract=_build_tool_contract(tool),
                enabled=tool.enabled,
                version=tool.version or 1,
            )
            session.add(capability)
        else:
            capability.name = tool.name
            capability.logical_op_name = tool.name
            capability.description = tool.description or tool.purpose or ""
            capability.tags = tool.tags or []
            capability.consumes = tool.consumes or []
            capability.produces = tool.produces or []
            capability.contract = _build_tool_contract(tool)
            capability.enabled = tool.enabled
            capability.version = tool.version or 1

        await session.flush()

        # One default provider per tool, one endpoint per provider.
        provider = (
            await session.execute(
                select(ProviderModel).where(
                    ProviderModel.capability_id == tool.id
                ).limit(1)
            )
        ).scalars().first()
        if provider is None:
            provider = ProviderModel(
                capability_id=tool.id,
                name=f"{tool.name}_provider",
                description=f"Default provider for {tool.name}",
                privacy_level="low",
                retry_policy="default",
                enabled=tool.enabled,
            )
            session.add(provider)
            await session.flush()

        endpoint = (
            await session.execute(
                select(EndpointModel).where(
                    EndpointModel.provider_id == provider.id
                ).limit(1)
            )
        ).scalars().first()
        url = tool.mcp_server_url or tool.endpoint_url or ""
        if endpoint is None:
            endpoint = EndpointModel(
                provider_id=provider.id,
                url=url,
                http_method=tool.http_method or "GET",
                auth_type=tool.auth_type or "none",
                weight=1,
                enabled=tool.enabled,
            )
            session.add(endpoint)
        else:
            endpoint.url = url
            endpoint.http_method = tool.http_method or "GET"
            endpoint.auth_type = tool.auth_type or "none"
            endpoint.enabled = tool.enabled

        await session.flush()

    async def get(
        self,
        session: AsyncSession,
        tool_id: uuid.UUID,
    ) -> ToolRead | None:
        """Get a single tool by id (any enabled state)."""
        tool = await self._get_model(session, tool_id)
        return _tool_to_read(tool) if tool else None

    async def list(  # noqa: PLR0913
        self,
        session: AsyncSession,
        tags: list[str] | None = None,
        category: str | None = None,
        enabled: bool | None = True,
        page: int = 1,
        page_size: int = 20,
    ) -> ToolList:
        """List tools with optional filters and pagination."""
        query = select(Tool)

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
        tools = result.scalars().all()

        return ToolList(
            items=[_tool_to_read(t) for t in tools],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def search_semantic(
        self,
        session: AsyncSession,
        query: str,
        k: int = 10,
    ) -> list[ToolSearchResult]:
        """Search tools by semantic similarity using pgvector cosine distance."""
        query_vector = (await self._generate_embedding(query)) or []
        if not query_vector:
            return []

        vector_literal = json.dumps(query_vector)
        sql = text(
            "SELECT id, embedding <=> :query_vec AS distance "
            "FROM tool "
            "WHERE enabled = true AND embedding IS NOT NULL "
            "ORDER BY distance "
            "LIMIT :k"
        )
        rows = await session.execute(
            sql,
            {"query_vec": vector_literal, "k": k},
        )

        tool_ids = []
        scores: dict[uuid.UUID, float] = {}
        for row in rows.fetchall():
            tid: uuid.UUID = row[0]
            distance: float = row[1]
            tool_ids.append(tid)
            scores[tid] = round(1.0 - distance, 4)

        if not tool_ids:
            return []

        tools_result = await session.execute(select(Tool).where(Tool.id.in_(tool_ids)))
        tools_map = {t.id: t for t in tools_result.scalars().all()}

        return [
            ToolSearchResult(tool=_tool_to_read(tools_map[tid]), score=scores[tid])
            for tid in tool_ids
            if tid in tools_map
        ]

    @staticmethod
    def _validate_no_python_code(data: ToolCreate) -> None:
        """Reject tool definitions that contain Python code references."""
        try:
            keywords = frozenset(get_settings().tools.python_code_keywords)
        except Exception:
            from nexus.config.settings import ToolSettings
            keywords = frozenset(ToolSettings().python_code_keywords)
        schemas_to_check = {
            "input_schema": data.input_schema,
            "output_schema": data.output_schema,
            "validation_rules": data.validation_rules,
        }
        for field_name, schema in schemas_to_check.items():
            if schema and isinstance(schema, dict):
                for key in schema:
                    if key.lower() in keywords:
                        raise ValueError(
                            f"Tool '{data.name}' contains Python code reference "
                            f"'{key}' in {field_name} — rejected"
                        )
                props = schema.get("properties", {})
                if isinstance(props, dict):
                    for prop_key in props:
                        if prop_key.lower() in keywords:
                            raise ValueError(
                                f"Tool '{data.name}' contains Python code reference "
                                f"'{prop_key}' in {field_name}.properties — rejected"
                            )

    @staticmethod
    def _validate_json_schema(schema: dict[str, Any]) -> None:
        """Validate that the schema matches JSON Schema Draft 7 or later."""
        if not schema:
            return
        schema_uri = schema.get("$schema", "")
        if schema_uri and "draft-07" not in schema_uri and "draft-20" not in schema_uri:
            logger.warning(
                "tool.schema_version_unknown",
                schema_uri=schema_uri,
                hint="Expected JSON Schema Draft 7 or later",
            )

    async def test_http_connection(
        self,
        tool: ToolRead,
        sample_input: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Make a real HTTP call to validate tool connectivity."""
        settings = get_settings()
        sandbox_config_allowed = settings.tools.allowed_hosts

        if tool.rate_limit_per_minute is not None and tool.rate_limit_per_minute > 0:
            redis = get_redis_client()
            if redis is not None:
                rl_key = f"tool:rl:test:{tool.id}"
                limiter = TokenBucketRateLimiter(
                    redis,
                    rate=tool.rate_limit_per_minute / 60.0,
                    capacity=float(tool.rate_limit_per_minute),
                )
                try:
                    await limiter.acquire(rl_key, raise_on_limit=True)
                except RateLimitError as exc:
                    return ToolResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        status="rate_limited",
                        error=str(exc),
                        duration_ms=0,
                    )

        try:
            check_allowed_host(tool.endpoint_url, sandbox_config_allowed)
        except Exception as exc:
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=f"Sandbox blocked: {exc}",
                duration_ms=0,
            )

        start = time.perf_counter()
        try:
            # Resolve URL template placeholders (e.g. {id} → actual value)
            import re as _re
            url = tool.endpoint_url
            params = dict(sample_input or {})
            if "{" in url and sample_input:
                for match in _re.finditer(r"\{(\w+)\}", url):
                    param = match.group(1)
                    if param in sample_input:
                        url = url.replace(match.group(0), str(sample_input[param]))
                        params.pop(param, None)

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                method = tool.http_method.lower()
                if method == "get":
                    resp = await client.get(url, params=params or None)
                else:
                    resp = await client.request(
                        method, url, json=params or None
                    )
                if resp.status_code >= 400:
                    resp.raise_for_status()
                data = resp.json() if resp.text else None
        except httpx.TimeoutException:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="timeout",
                error="Test connection timed out",
                duration_ms=duration_ms,
            )
        except httpx.ConnectError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=f"Connection refused: {exc}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=f"Test connection failed: {exc}",
                duration_ms=duration_ms,
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            tool_id=tool.id,
            tool_name=tool.name,
            status="success",
            http_status=resp.status_code,
            data=data if isinstance(data, dict) else {"result": data},
            duration_ms=duration_ms,
            raw_response_excerpt=resp.text[:2000] if resp.text else None,
            response_headers=dict(resp.headers),
        )

    async def _generate_embedding(self, text: str) -> list[float] | None:
        # Check text-hash cache in Redis
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        cache_key = f"embed:{text_hash}"
        try:
            from nexus.redis_client.client import get_redis_client  # noqa: PLC0415
            redis = get_redis_client()
            if redis is not None:
                import json as _json
                cached = await redis.get(cache_key)
                if cached:
                    return _json.loads(cached)
        except Exception:
            pass
        try:
            embeddings = await self._llm.embed(EMBEDDING_MODEL, [text])
            if embeddings and embeddings[0]:
                result = embeddings[0]
                # Cache in Redis (TTL 1 hour)
                try:
                    import json as _json
                    if redis is not None:
                        await redis.setex(cache_key, 3600, _json.dumps(result))
                except Exception:
                    pass
                return result
        except Exception:
            logger.warning("embedding.failed", exc_info=True)
        return None

    @staticmethod
    async def _get_model(
        session: AsyncSession,
        tool_id: uuid.UUID,
    ) -> Tool | None:
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Tool)
            .where(Tool.id == tool_id)
            .options(selectinload(Tool.executions))
        )
        return result.scalar_one_or_none()
