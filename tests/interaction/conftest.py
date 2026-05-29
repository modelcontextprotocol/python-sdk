"""Shared fixtures for the interaction suite."""

from collections.abc import Iterator

import pytest
from sse_starlette.sse import AppStatus

from tests.interaction._connect import Connect, connect_in_memory, connect_over_sse, connect_over_streamable_http


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "requirement(id): tag a test as covering an entry in tests/interaction/_requirements.py"
    )
    # v1's streamable-HTTP server transport leaks a handful of anyio memory streams on teardown
    # (e.g. `_handle_get_request` only closes `sse_stream_reader` on the exception path; the
    # session manager's per-session task-group cancel can race the per-request cleanup). v1's own
    # tests run the transport in a separate process and so never observe these `__del__`-time
    # ResourceWarnings; running in-process via the streaming bridge does. The fixes live in `src/`
    # on `main` and are out of scope for this tests-only backport. The filters below are scoped to
    # anyio's `MemoryObject*Stream` leak signature so an unrelated leak still fails the suite.
    config.addinivalue_line(
        "filterwarnings", "ignore:.*MemoryObject(Send|Receive)Stream:pytest.PytestUnraisableExceptionWarning"
    )
    config.addinivalue_line("filterwarnings", "ignore:.*MemoryObject(Send|Receive)Stream:ResourceWarning")


_FACTORIES: dict[str, Connect] = {
    "in-memory": connect_in_memory,
    "streamable-http": connect_over_streamable_http,
    "sse": connect_over_sse,
}


@pytest.fixture(autouse=True)
def _reset_sse_starlette_exit_event() -> Iterator[None]:
    """Reset sse-starlette's module-global exit Event after each test.

    sse-starlette <3.0 stores an `anyio.Event` on the `AppStatus` class the first time an
    `EventSourceResponse` runs; that Event is bound to the test's event loop and breaks every
    subsequent in-process SSE response (RuntimeError "bound to a different event loop", surfacing
    as 5-second timeouts in `connect_with_oauth` and "Child exited" on the [sse] leg). v1's own
    transport tests run uvicorn in a subprocess and so never share a process across event loops.
    sse-starlette 3.x switched to a ContextVar (`_exit_event_context`) and has no such attribute.
    """
    yield
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        AppStatus.should_exit_event = None  # pragma: lax no cover


@pytest.fixture(params=sorted(_FACTORIES))
def connect(request: pytest.FixtureRequest) -> Connect:
    """The transport-parametrized connection factory: a test using it runs once per transport.

    Tests that are tied to one transport (the wire-recording tests, the bare-ClientSession tests,
    the transport-specific tests under transports/) do not use this fixture and connect directly.
    """
    transport_name = request.param
    assert isinstance(transport_name, str)
    return _FACTORIES[transport_name]
