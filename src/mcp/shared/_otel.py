"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer
from opentelemetry.trace.span import Span

_tracer = get_tracer("mcp-python-sdk")


@contextmanager
def otel_span(
    name: str,
    *,
    kind: SpanKind,
    attributes: dict[str, Any] | None = None,
    context: Context | None = None,
    record_exception: bool = True,
    set_status_on_exception: bool = True,
) -> Generator[Span]:
    """Create an OTel span."""
    with _tracer.start_as_current_span(
        name,
        kind=kind,
        attributes=attributes,
        context=context,
        record_exception=record_exception,
        set_status_on_exception=set_status_on_exception,
    ) as span:
        yield span


def inject_trace_context(meta: dict[str, Any]) -> None:
    """Inject W3C trace context (traceparent/tracestate) into a `_meta` dict."""
    inject(meta)


def extract_trace_context(meta: Mapping[str, Any]) -> Context:
    """Extract W3C trace context from a `_meta` dict."""
    try:
        return extract(meta)
    except (ValueError, TypeError):
        # If the traceparent is malformed, degrade to no parent rather than failing the request.
        return Context()
