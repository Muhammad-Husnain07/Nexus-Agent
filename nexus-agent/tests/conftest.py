"""Shared test fixtures for compiler golden tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.compiler.resolver import CapabilityResolver


@pytest.fixture
def mock_db_session():
    """Return an AsyncMock that stands in for the DB session.

    ``CapabilityResolver.resolve()`` gets a stub ``EndpointModel``
    matching the ``get_weather`` capability.
    """
    from nexus.db.models.registry import CapabilityModel, EndpointModel, ProviderModel

    endpoint = EndpointModel(
        id="00000000-0000-0000-0000-000000000000",
        provider_id="00000000-0000-0000-0000-000000000000",
        url="https://api.open-meteo.com/v1/forecast",
        http_method="GET",
        auth_type="none",
        cost_per_call=0.0,
        latency_p99_ms=1000,
        supports_batch=False,
        enabled=True,
        weight=1,
    )
    provider = ProviderModel(
        id="00000000-0000-0000-0000-000000000000",
        capability_id="00000000-0000-0000-0000-000000000000",
        name="open_meteo",
        enabled=True,
    )
    provider.endpoints = [endpoint]
    capability = CapabilityModel(
        id="00000000-0000-0000-0000-000000000000",
        name="get_weather",
        logical_op_name="get_weather",
        enabled=True,
    )
    capability.providers = [provider]

    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=capability)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session
