from collections.abc import Callable
from typing import Any

import pytest

from mcp.server.mcpserver.context import Context

MakeContext = Callable[..., Context[Any, Any]]


@pytest.fixture
def make_context() -> MakeContext:
    """Factory fixture for creating Context instances in tests.

    Centralizes Context construction so that tests don't break if the
    Context.__init__ signature changes in later iterations.
    """

    def _make(**kwargs: Any) -> Context[Any, Any]:
        return Context(**kwargs)

    return _make
