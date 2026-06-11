"""Shared configuration for the experimental tasks suite."""

from pathlib import Path

import pytest

_HERE = Path(__file__).parent

# The tasks suite intentionally exercises the deprecated experimental tasks API.
_TASKS_DEPRECATION_IGNORE = pytest.mark.filterwarnings(
    "ignore:The experimental tasks API is deprecated:DeprecationWarning"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(_TASKS_DEPRECATION_IGNORE)
