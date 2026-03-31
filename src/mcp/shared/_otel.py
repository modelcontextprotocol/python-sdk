"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")


@contextmanager
def otel_span(
    name: str,
    *,
    kind: str = "INTERNAL",
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Create an OTel span."""
    span_kind = getattr(SpanKind, kind, SpanKind.INTERNAL)
    with _tracer.start_as_current_span(name, kind=span_kind, attributes=attributes) as span:
        yield span
