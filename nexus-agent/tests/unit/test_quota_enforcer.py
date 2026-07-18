"""Tests for QuotaEnforcer with fakeredis."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from nexus.errors import QuotaExceededError
from nexus.security.quota import QuotaEnforcer


class TestQuotaEnforcer:
    """Test quota enforcement with fakeredis."""

    @pytest.fixture
    def tenant_id(self) -> uuid.UUID:
        return uuid.UUID("11111111-1111-4111-8111-111111111111")

    async def test_check_tool_count_under_limit(self, tenant_id: uuid.UUID) -> None:
        enforcer = QuotaEnforcer(redis_client=None)
        await enforcer.check_tool_count(tenant_id, 5, 50)

    async def test_check_tool_count_exceeded(self, tenant_id: uuid.UUID) -> None:
        enforcer = QuotaEnforcer(redis_client=None)
        with pytest.raises(QuotaExceededError):
            await enforcer.check_tool_count(tenant_id, 50, 50)

    async def test_check_session_creation_no_redis(self, tenant_id: uuid.UUID) -> None:
        with patch("nexus.security.quota.get_redis_client", return_value=None):
            enforcer = QuotaEnforcer()
            await enforcer.check_session_creation(tenant_id, 1000)

    async def test_check_session_creation_with_redis(
        self, tenant_id: uuid.UUID, fake_redis
    ) -> None:
        enforcer = QuotaEnforcer(redis_client=fake_redis)
        await enforcer.check_session_creation(tenant_id, 1000)

    async def test_check_token_usage_no_redis(self, tenant_id: uuid.UUID) -> None:
        with patch("nexus.security.quota.get_redis_client", return_value=None):
            enforcer = QuotaEnforcer()
            await enforcer.check_token_usage(tenant_id, 100, 50000)

    async def test_check_token_usage_exceeded(
        self, tenant_id: uuid.UUID, fake_redis
    ) -> None:
        enforcer = QuotaEnforcer(redis_client=fake_redis)
        with pytest.raises(QuotaExceededError):
            await enforcer.check_token_usage(tenant_id, 100, 50)

    async def test_check_cost_no_redis(self, tenant_id: uuid.UUID) -> None:
        with patch("nexus.security.quota.get_redis_client", return_value=None):
            enforcer = QuotaEnforcer()
            await enforcer.check_cost(tenant_id, 1.0, 50.0)

    async def test_none_redis_skips_checks(self, tenant_id: uuid.UUID) -> None:
        with patch("nexus.security.quota.get_redis_client", return_value=None):
            enforcer = QuotaEnforcer()
            await enforcer.check_session_creation(tenant_id, 1)
            await enforcer.check_token_usage(tenant_id, 9999, 1)
            await enforcer.check_cost(tenant_id, 99.0, 1.0)
