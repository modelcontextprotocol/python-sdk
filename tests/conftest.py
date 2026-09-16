import os
from collections.abc import AsyncIterator, Iterator

import httpcore2 as _httpcore2
import pytest
from blockbuster import BlockBuster

# OpenTelemetry's `set_tracer_provider` is set-once per process, so the suite
# uses a single span-capture mechanism: logfire's `capfire` fixture (its
# `configure()` swaps span processors on repeat calls rather than re-setting
# the provider). Logfire's default `distributed_tracing=None` emits a
# RuntimeWarning + diagnostic span when incoming W3C trace context is
# extracted; several tests exercise that propagation deliberately, so opt in
# suite-wide. Set before logfire is imported anywhere.
os.environ.setdefault("LOGFIRE_DISTRIBUTED_TRACING", "true")

import opentelemetry.trace  # noqa: E402  (env var must be set before logfire import below)
from logfire.testing import CaptureLogfire  # noqa: E402

import mcp.shared._otel  # noqa: E402

# Load httpx2's lazy default transport before BlockBuster starts.
del _httpcore2


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def blockbuster() -> Iterator[None]:
    bb = BlockBuster(["mcp", "mcp_types"])
    # Coverage reads source files while collecting data.
    bb.functions["os.stat"].can_block_in("coverage/python.py", "get_python_source")
    bb.functions["io.BufferedReader.read"].can_block_in("coverage/python.py", "read_python_source")
    # jsonschema discovers its bundled schemas during its first import.
    bb.functions["os.listdir"].can_block_in("/jsonschema_specifications/_core.py", "_schemas")
    bb.functions["os.scandir"].can_block_in("/jsonschema_specifications/_core.py", "_schemas")
    bb.functions["io.TextIOWrapper.read"].can_block_in("/jsonschema_specifications/_core.py", "_schemas")
    # These public synchronous conversions read the media file by design.
    bb.functions["io.BufferedReader.read"].can_block_in(
        "mcp/server/mcpserver/utilities/types.py", ("to_image_content", "to_audio_content")
    )
    bb.activate()
    try:
        yield
    finally:
        bb.deactivate()


@pytest.fixture(scope="module", autouse=True)
async def _module_runner_lease(anyio_backend: str) -> AsyncIterator[None]:
    """Share one event loop across each module's tests instead of one per test.

    anyio's pytest plugin tears its runner down whenever the last lease is
    released, so with only function-scoped async fixtures every async test
    creates and destroys its own event loop. On Windows each loop's self-pipe
    is an emulated loopback-TCP socketpair, and churning thousands of those per
    run can transiently exhaust kernel socket buffers — surfacing in CI as
    `OSError: [WinError 10055]` raised from `asyncio.new_event_loop()` before
    an arbitrary test's body even starts. Holding a module-scoped lease caps
    the churn at one loop per module per xdist worker.

    Modules that parametrize `anyio_backend` or call `trio.run(...)` directly
    must shadow this fixture with a sync no-op: a module-scoped lease cannot
    depend on the function-scoped parameter (pytest raises ScopeMismatch at
    setup), and the lease's live asyncio loop lingers over direct trio runs,
    whose signal handling collides with the loop's wakeup fd on Windows. The
    lease also makes sniffio report asyncio to the module's sync tests, so a
    sync test must not call `anyio.run()` itself.
    """
    yield


@pytest.fixture(name="capfire")
def _capfire_isolated(capfire: CaptureLogfire) -> Iterator[CaptureLogfire]:
    """Override of logfire's `capfire` that scopes the MCP tracer to the test.

    `capfire` installs a real tracer provider, and logfire's proxy machinery
    mutates the cached `mcp.shared._otel._tracer` to delegate to it for the
    rest of the process. Without isolation, every subsequent test in the same
    worker would emit real spans, and `send_raw_request` would inject a real
    `traceparent` into outbound `_meta`, breaking the interaction-suite
    snapshots that pin `_meta={}` under a no-op tracer.

    Setup points `_tracer` at the now-live provider so MCP spans record;
    teardown replaces it with a `NoOpTracer`.
    """
    mcp.shared._otel._tracer = opentelemetry.trace.get_tracer_provider().get_tracer("mcp-python-sdk")
    try:
        yield capfire
    finally:
        mcp.shared._otel._tracer = opentelemetry.trace.NoOpTracer()
