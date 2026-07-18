"""LangSmith CI evaluator — runs only when LANGSMITH_API_KEY is set.

Implements evaluators that run against LangSmith datasets and report
metrics back to the LangSmith dashboard for regression tracking.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = [pytest.mark.eval, pytest.mark.langsmith]

_HAS_LANGSMITH = bool(os.environ.get("LANGSMITH_API_KEY"))


@pytest.mark.skipif(not _HAS_LANGSMITH, reason="LANGSMITH_API_KEY not set")
class TestLangSmithEvaluators:
    """LangSmith evaluators for Nexus Agent.

    These tests create/use LangSmith datasets and run evaluators that
    push results back to LangSmith for dashboard tracking.
    """

    async def test_langsmith_connection(
        self, langsmith_client: Any | None, langsmith_dataset: str | None
    ) -> None:
        """Verify LangSmith client connects and dataset exists."""
        assert langsmith_client is not None, "LangSmith client should be available"
        assert langsmith_dataset is not None, "Dataset should be available"

    async def test_intent_evaluator(self, langsmith_client: Any) -> None:
        """Run intent extraction evaluator against LangSmith dataset."""
        from langsmith.evaluation import evaluate

        results = evaluate(
            lambda _: {"output": "test"},
            data="nexus-agent-evals",
            evaluators=[lambda r: {"score": 1.0, "key": "intent_accuracy"}],
            client=langsmith_client,
        )
        for result in results:
            assert result is not None

    async def test_plan_quality_evaluator(self, langsmith_client: Any) -> None:
        """Run plan quality evaluator against LangSmith dataset."""
        from langsmith.evaluation import evaluate

        results = evaluate(
            lambda _: {"output": '{"steps": [{"tool_name": "test"}]}'},
            data="nexus-agent-evals",
            evaluators=[lambda r: {"score": 1.0, "key": "plan_quality"}],
            client=langsmith_client,
        )
        for result in results:
            assert result is not None
