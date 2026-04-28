"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")


@contextmanager
def otel_span(
    name: str,
    *,
    kind: SpanKind,
    attributes: dict[str, Any] | None = None,
    context: Context | None = None,
) -> Iterator[Any]:
    """Create an OTel span."""
    with _tracer.start_as_current_span(name, kind=kind, attributes=attributes, context=context) as span:
        yield span


def inject_trace_context(meta: dict[str, Any]) -> None:
    """Inject W3C trace context (traceparent/tracestate) into a `_meta` dict."""
    inject(meta)


def extract_trace_context(meta: dict[str, Any]) -> Context:
    """Extract W3C trace context from a `_meta` dict."""
    return extract(meta)
