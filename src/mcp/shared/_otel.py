"""OpenTelemetry helpers for MCP.

Provides a context manager that creates an OpenTelemetry span when
``opentelemetry-api`` is installed, or acts as a no-op otherwise.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@functools.lru_cache(maxsize=1)
def _get_tracer() -> Any:
    """Return the OTel tracer for ``mcp``, or ``None``."""
    try:
        from opentelemetry.trace import get_tracer

        return get_tracer("mcp-python-sdk")
    except ImportError:
        return None


@contextmanager
def otel_span(
    name: str,
    *,
    kind: str = "INTERNAL",
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Create an OTel span if ``opentelemetry-api`` is installed, else no-op."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry.trace import SpanKind

    span_kind = getattr(SpanKind, kind, SpanKind.INTERNAL)
    with tracer.start_as_current_span(name, kind=span_kind, attributes=attributes) as span:
        yield span
