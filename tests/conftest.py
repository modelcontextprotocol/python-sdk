from collections.abc import Iterator

import pytest
from sse_starlette.sse import AppStatus


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_sse_starlette_exit_event() -> Iterator[None]:
    """sse-starlette<2 caches a module-level anyio.Event on AppStatus. Clear it
    around each test so it is never bound to a closed event loop: any test that
    serves an SSE response in process would otherwise inherit the event a
    previous test created on another loop. Clearing it afterwards matters too,
    because later test modules fork uvicorn subprocesses on Linux and would
    otherwise inherit a stale event."""

    def clear() -> None:
        if hasattr(AppStatus, "should_exit_event"):  # pragma: no cover
            setattr(AppStatus, "should_exit_event", None)

    clear()
    yield
    clear()
