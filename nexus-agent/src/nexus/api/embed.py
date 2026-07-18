"""Embed API — CRUD for embed widget tokens and analytics.

All endpoints require ``TOOLS_REGISTER`` (admin) permission.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.depends import TenantDep
from nexus.config.settings import get_settings
from nexus.db.base import get_session
from nexus.db.models.embed import EmbedConfig

logger = structlog.get_logger("nexus.api.embed")

router = APIRouter(prefix="/embeds", tags=["embeds"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

EMBED_THEME = Literal["light", "dark", "custom"]


class EmbedCreatePayload(BaseModel):
    """Request body for creating a new embed widget."""

    name: str = Field(default="", description="Optional widget label")
    allowed_domains: list[str] = Field(
        default_factory=list, description="Allowed Origin domains for CORS"
    )
    theme: EMBED_THEME = Field(default="light", description="Widget theme")
    primary_color: str = Field(default="#2563eb", description="Primary brand color")
    welcome_message: str = Field(
        default="Hello! How can I help you today?",
        description="Initial greeting message",
    )
    max_height: int = Field(default=600, ge=200, le=1200, description="Max widget height")
    max_width: int = Field(default=380, ge=200, le=800, description="Max widget width")
    custom_css: str = Field(default="", description="Custom CSS (base64-encoded)")
    rate_limit: int = Field(default=30, ge=1, le=300, description="Messages per minute")
    analytics_enabled: bool = Field(default=True, description="Track usage")


class EmbedRead(BaseModel):
    """Embed configuration returned by the API (token excluded)."""

    id: uuid.UUID
    name: str
    allowed_domains: list[str]
    theme: str
    primary_color: str
    welcome_message: str
    max_height: int
    max_width: int
    custom_css: str
    rate_limit: int
    analytics_enabled: bool
    is_revoked: bool
    message_count: int
    active_sessions: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmbedCreateResponse(BaseModel):
    """Response returned after creating a new embed widget."""

    embed_id: uuid.UUID
    token: str
    script_url: str
    created_at: datetime


class EmbedAnalytics(BaseModel):
    """Usage analytics for an embed widget."""

    message_count: int
    active_sessions: int
    avg_session_duration_s: float


class EmbedUpdatePayload(BaseModel):
    """Request body for updating an embed widget. All fields optional."""

    name: str | None = None
    allowed_domains: list[str] | None = None
    theme: EMBED_THEME | None = None
    primary_color: str | None = None
    welcome_message: str | None = None
    max_height: int | None = None
    max_width: int | None = None
    custom_css: str | None = None
    rate_limit: int | None = None
    analytics_enabled: bool | None = None


def _script_url(token: str) -> str:
    settings = get_settings()
    base = settings.server.host or "http://localhost:8000"
    return f"{base}/embed/widget.js?token={token}"


async def _get_embed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    embed_id: uuid.UUID,
) -> EmbedConfig:
    result = await session.execute(
        select(EmbedConfig).where(
            EmbedConfig.id == embed_id,
            EmbedConfig.tenant_id == tenant_id,
        )
    )
    embed = result.scalar_one_or_none()
    if embed is None:
        raise HTTPException(status_code=404, detail="Embed not found")
    return embed


@router.post("", response_model=EmbedCreateResponse, status_code=201)
async def create_embed(
    payload: EmbedCreatePayload,
    session: SessionDep,
    tenant_id: TenantDep,
) -> EmbedCreateResponse:
    """Create a new embed widget with a scoped token."""
    token = secrets.token_urlsafe(48)
    embed = EmbedConfig(
        tenant_id=tenant_id,
        name=payload.name,
        token=token,
        allowed_domains=payload.allowed_domains,
        theme=payload.theme,
        primary_color=payload.primary_color,
        welcome_message=payload.welcome_message,
        max_height=payload.max_height,
        max_width=payload.max_width,
        custom_css=payload.custom_css,
        rate_limit=payload.rate_limit,
        analytics_enabled=payload.analytics_enabled,
    )
    session.add(embed)
    await session.flush()

    logger.info("embed.created", embed_id=str(embed.id), token_prefix=token[:12])

    return EmbedCreateResponse(
        embed_id=embed.id,
        token=token,
        script_url=_script_url(token),
        created_at=embed.created_at,
    )


@router.get("/{embed_id}", response_model=EmbedRead)
async def get_embed(
    embed_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
) -> EmbedRead:
    """Get embed configuration by ID."""
    embed = await _get_embed(session, tenant_id, embed_id)
    return EmbedRead.model_validate(embed)


@router.put("/{embed_id}", response_model=EmbedRead)
async def update_embed(
    embed_id: uuid.UUID,
    payload: EmbedUpdatePayload,
    session: SessionDep,
    tenant_id: TenantDep,
) -> EmbedRead:
    """Update embed configuration."""
    embed = await _get_embed(session, tenant_id, embed_id)
    update_dict = payload.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(embed, field, value)
    await session.flush()
    logger.info("embed.updated", embed_id=str(embed.id))
    return EmbedRead.model_validate(embed)


@router.delete("/{embed_id}", status_code=204)
async def revoke_embed(
    embed_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
) -> None:
    """Revoke an embed token immediately."""
    embed = await _get_embed(session, tenant_id, embed_id)
    embed.is_revoked = True
    await session.flush()
    logger.info("embed.revoked", embed_id=str(embed.id))


@router.get("/{embed_id}/analytics", response_model=EmbedAnalytics)
async def embed_analytics(
    embed_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
) -> EmbedAnalytics:
    """Return usage analytics for an embed widget."""
    embed = await _get_embed(session, tenant_id, embed_id)
    return EmbedAnalytics(
        message_count=embed.message_count,
        active_sessions=embed.active_sessions,
        avg_session_duration_s=0.0,
    )
