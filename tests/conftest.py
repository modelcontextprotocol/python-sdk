import os
from collections.abc import Iterator

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
