import anyio
import pytest
import sse_starlette
from packaging import version


@pytest.fixture
def anyio_backend():
    return "asyncio"


SSE_STARLETTE_VERSION = version.parse(sse_starlette.__version__)
NEEDS_RESET = SSE_STARLETTE_VERSION < version.parse("3.0.0")


@pytest.fixture(autouse=True)
def reset_sse_app_status():
    """Reset sse-starlette's global AppStatus singleton before each test.

    AppStatus.should_exit_event is a global asyncio.Event that gets bound to
    an event loop. This ensures each test gets a fresh Event and prevents
    RuntimeError("bound to a different event loop") during parallel test
    execution with pytest-xdist.

    NOTE: This fixture is only necessary for sse-starlette < 3.0.0.
    Version 3.0+ eliminated the global state issue entirely by using
    context-local events instead of module-level singletons, providing
    automatic test isolation without manual cleanup.

    See <https://github.com/sysid/sse-starlette/pull/141> for more details.
    """
    if not NEEDS_RESET:
        yield
        return

    # lazy import to avoid import errors
    from sse_starlette.sse import AppStatus

    # Setup: Reset before test
    AppStatus.should_exit_event = anyio.Event()  # type: ignore[attr-defined]

    yield

    # Teardown: Reset after test to prevent contamination
    AppStatus.should_exit_event = anyio.Event()  # type: ignore[attr-defined]
