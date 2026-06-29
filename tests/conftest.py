import os
from collections.abc import Iterator

import pytest

# OTel's `set_tracer_provider` is set-once per process, so all span capture goes through logfire's `capfire`
# fixture. Logfire's default `distributed_tracing=None` emits a RuntimeWarning when incoming W3C trace context
# is extracted; tests exercise that propagation deliberately, so opt in suite-wide before logfire is imported.
os.environ.setdefault("LOGFIRE_DISTRIBUTED_TRACING", "true")

import opentelemetry.trace  # noqa: E402  (env var must be set before logfire import below)
from logfire.testing import CaptureLogfire  # noqa: E402

import mcp.shared._otel  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(name="capfire")
def _capfire_isolated(capfire: CaptureLogfire) -> Iterator[CaptureLogfire]:
    """Override of logfire's `capfire` that scopes the MCP tracer to the test.

    Logfire's proxy machinery mutates the cached `mcp.shared._otel._tracer` to delegate to
    `capfire`'s provider for the rest of the process. Without the `NoOpTracer` teardown, later
    tests would emit real spans and `send_raw_request` would inject a real `traceparent` into
    outbound `_meta`, breaking interaction-suite snapshots that pin `_meta={}`.
    """
    mcp.shared._otel._tracer = opentelemetry.trace.get_tracer_provider().get_tracer("mcp-python-sdk")
    try:
        yield capfire
    finally:
        mcp.shared._otel._tracer = opentelemetry.trace.NoOpTracer()
