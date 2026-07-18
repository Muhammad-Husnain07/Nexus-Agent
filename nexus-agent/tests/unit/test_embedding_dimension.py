"""Regression test: embedding dimension validation in LLMClient.embed().

Verifies that the dimension check in embed() rejects mismatched vectors
and accepts matching ones.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_all() -> None:
    """Set embedding_dimensions=768 and mock aembedding for all tests."""
    with patch("nexus.config.settings.get_settings") as mock_settings:
        settings = MagicMock()
        settings.llm.embedding_dimensions = 768
        mock_settings.return_value = settings
        with patch("litellm.aembedding") as mock_aembed:
            yield mock_aembed


@pytest.mark.asyncio
async def test_embed_accepts_768_dim(_patch_all: AsyncMock) -> None:
    """768-dim vector must pass validation when embedding_dimensions=768."""
    from nexus.llm.client import LLMClient

    client = LLMClient()
    mock_provider = MagicMock()
    mock_provider.api_key.get_secret_value.return_value = ""
    type(mock_provider.config).supports_output_dimensions = PropertyMock(return_value=False)

    mock_response = MagicMock()
    item = MagicMock()
    item.__getitem__ = lambda self, k, v=[0.1] * 768: v if k == "embedding" else None
    mock_response.data = [item]
    _patch_all.return_value = mock_response

    with patch.object(client.registry, "resolve_provider", return_value=(mock_provider, "test")):
        result = await client.embed("test-model", ["hello"])
        assert len(result[0]) == 768


@pytest.mark.asyncio
async def test_embed_rejects_1536_dim(_patch_all: AsyncMock) -> None:
    """1536-dim vector must raise ValueError when embedding_dimensions=768."""
    from nexus.llm.client import LLMClient

    client = LLMClient()
    mock_provider = MagicMock()
    mock_provider.api_key.get_secret_value.return_value = ""
    type(mock_provider.config).supports_output_dimensions = PropertyMock(return_value=False)

    mock_response = MagicMock()
    item = MagicMock()
    item.__getitem__ = lambda self, k, v=[0.1] * 1536: v if k == "embedding" else None
    mock_response.data = [item]
    _patch_all.return_value = mock_response

    with patch.object(client.registry, "resolve_provider", return_value=(mock_provider, "test")):
        with pytest.raises(ValueError, match="returned a 1536-dim.*EMBEDDING_DIMENSIONS=768"):
            await client.embed("test-model", ["hello"])
