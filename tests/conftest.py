import os

import pytest

# OpenTelemetry's `set_tracer_provider` is set-once per process, so the suite
# uses a single span-capture mechanism: logfire's `capfire` fixture (its
# `configure()` swaps span processors on repeat calls rather than re-setting
# the provider). Logfire's default `distributed_tracing=None` emits a
# RuntimeWarning + diagnostic span when incoming W3C trace context is
# extracted; several tests exercise that propagation deliberately, so opt in
# suite-wide. Set before logfire is imported anywhere.
os.environ.setdefault("LOGFIRE_DISTRIBUTED_TRACING", "true")


@pytest.fixture
def anyio_backend():
    return "asyncio"
