from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode

_tracer = trace.get_tracer("mcp")

_EXCLUDED_METHODS: frozenset[str] = frozenset({"notifications/message"})

# Semantic convention attribute keys
ATTR_MCP_METHOD_NAME = "mcp.method.name"
ATTR_ERROR_TYPE = "error.type"

# Methods that have a meaningful target name in params
_TARGET_PARAM_KEY: dict[str, str] = {
    "tools/call": "name",
    "prompts/get": "name",
    "resources/read": "uri",
}


def _extract_target(method: str, params: dict[str, Any] | None) -> str | None:
    """Extract the target (e.g. tool name, prompt name) from request params."""
    key = _TARGET_PARAM_KEY.get(method)
    if key is None or params is None:
        return None
    value = params.get(key)
    if isinstance(value, str):
        return value
    return None


def _build_span_name(method: str, target: str | None) -> str:
    """Build a span name like 'tools/call my_tool' or just 'ping'."""
    if target:
        return f"{method} {target}"
    return method


def start_client_span(method: str, params: dict[str, Any] | None) -> trace.Span | None:
    """Start a CLIENT span for an outgoing MCP request.

    Returns None if the method is excluded from tracing.
    """
    if method in _EXCLUDED_METHODS:
        return None

    target = _extract_target(method, params)
    span_name = _build_span_name(method, target)
    span = _tracer.start_span(
        span_name,
        kind=trace.SpanKind.CLIENT,
        attributes={ATTR_MCP_METHOD_NAME: method},
    )
    return span


def end_span_ok(span: trace.Span) -> None:
    """Mark a span as successful and end it."""
    span.set_status(StatusCode.OK)
    span.end()


def end_span_error(span: trace.Span, error: BaseException) -> None:
    """Mark a span as errored and end it."""
    span.set_status(StatusCode.ERROR, str(error))
    span.set_attribute(ATTR_ERROR_TYPE, type(error).__qualname__)
    span.end()
