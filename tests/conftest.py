import os
import sys
from collections.abc import AsyncIterator, Iterator

import anyio.lowlevel
import pytest

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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def _heal_gh106749(anyio_backend: str) -> AsyncIterator[None]:
    """Re-sync coverage's CTracer after every async test on CPython 3.11.

    CPython gh-106749: anyio delivers a task-group cancel via `coro.throw()`,
    which on 3.11 skips the outer await chain's `'call'` trace events.
    coverage.py's CTracer keys its frame stack on those events, so until the
    next `.send()` resumption, line events are misattributed and dropped. Under
    xdist a desync at the end of one test carries into the start of the next on
    the same worker; the missed lines move with worker test ordering.

    `cancel_shielded_checkpoint()` resumes via `.send()`, re-stamping the
    missing events. The shielded variant is a pure scheduling yield with no
    cancel delivery, so it cannot perturb a test's cancel-scope nesting. The
    `anyio_backend` dependency makes anyio's pytest plugin own this fixture so
    it runs in the test's task; sync tests skip it.
    """
    yield
    # The heal line itself runs while the tracer is desynced (that's the
    # point), so it cannot record its own execution; on non-3.11 the body is
    # never entered. Hence lax no cover on the whole tail.
    if sys.version_info[:2] == (3, 11):  # pragma: lax no cover
        await anyio.lowlevel.cancel_shielded_checkpoint()


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
