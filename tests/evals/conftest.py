"""Eval test fixtures — LangSmith integration + dataset loading.

When LANGSMITH_API_KEY is set, creates LangSmith datasets and evaluators.
Otherwise, uses local dataset JSON files for offline evaluation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

DATASETS_DIR = Path(__file__).parent / "datasets"

_HAS_LANGSMITH = bool(os.environ.get("LANGSMITH_API_KEY"))


def load_dataset(name: str) -> list[dict[str, Any]]:
    """Load an eval dataset from the datasets directory."""
    path = DATASETS_DIR / f"{name}.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def intent_examples() -> list[dict[str, Any]]:
    return load_dataset("intent_examples")


@pytest.fixture(scope="session")
def plan_scenarios() -> list[dict[str, Any]]:
    return load_dataset("plan_scenarios")


@pytest.fixture(scope="session")
def requirement_scenarios() -> list[dict[str, Any]]:
    return load_dataset("requirement_scenarios")


@pytest.fixture(scope="session")
def tool_selection_examples() -> list[dict[str, Any]]:
    return load_dataset("tool_selection_examples")


@pytest.fixture(scope="session")
def e2e_scenarios() -> list[dict[str, Any]]:
    return load_dataset("e2e_scenarios")


@pytest.fixture(scope="session")
def has_langsmith() -> bool:
    return _HAS_LANGSMITH


# ---------------------------------------------------------------------------
# LangSmith integration (only when API key is present)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def langsmith_client() -> Any | None:
    """Create a LangSmith client if credentials are available."""
    if not _HAS_LANGSMITH:
        return None
    try:
        from langsmith import Client
        return Client()
    except ImportError:
        return None


@pytest.fixture(scope="session")
def langsmith_dataset(langsmith_client: Any | None) -> str | None:
    """Create or get a LangSmith dataset for Nexus evals.

    Returns the dataset name or None if LangSmith is not configured.
    """
    if langsmith_client is None:
        return None
    dataset_name = "nexus-agent-evals"
    try:
        langsmith_client.create_dataset(
            dataset_name=dataset_name,
            description="Nexus Agent evaluation scenarios",
        )
    except Exception:
        pass  # dataset already exists
    return dataset_name


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for eval tests."""
    config.addinivalue_line("markers", "langsmith: tests that require LangSmith API access")
