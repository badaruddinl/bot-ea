from __future__ import annotations

from pathlib import Path

import pytest

SLOW_TEST_FILES = frozenset(
    {
        "test_goldm_deployment.py",
        "test_goldm_research_dataset.py",
        "test_goldm_research_environment.py",
        "test_goldm_research_folds.py",
        "test_goldm_research_import.py",
        "test_goldm_research_metrics.py",
        "test_goldm_research_network.py",
        "test_goldm_research_policy.py",
        "test_goldm_research_run.py",
        "test_goldm_research_stage_a.py",
    }
)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify historical/deployment matrices without editing legacy fixtures."""
    for item in items:
        if Path(str(item.path)).name in SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
