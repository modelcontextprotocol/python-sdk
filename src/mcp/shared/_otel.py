"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.context import Context
from opentelemetry.metrics import get_meter
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")
_meter = get_meter("mcp-python-sdk")

# Metrics as defined by the OTEL semconv https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/mcp.md
_DURATION_BUCKETS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]

_server_operation_duration = _meter.create_histogram(
    "mcp.server.operation.duration",
    unit="s",
    description=(
        "MCP request or notification duration as observed on the receiver "
        "from the time it was received until the result or ack is sent."
    ),
    explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
)

_server_session_duration = _meter.create_histogram(
    "mcp.server.session.duration",
    unit="s",
    description="The duration of the MCP session as observed on the MCP server.",
    explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
)


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


def record_server_operation_duration(
    duration_s: float,
    method: str,
    *,
    error_type: str | None = None,
    rpc_response_status_code: str | None = None,
    tool_name: str | None = None,
    prompt_name: str | None = None,
    mcp_protocol_version: str | None = None,
) -> None:
    """Record a data point for mcp.server.operation.duration."""
    attributes: dict[str, str] = {"mcp.method.name": method}
    if error_type is not None:
        attributes["error.type"] = error_type
    if rpc_response_status_code is not None:
        attributes["rpc.response.status_code"] = rpc_response_status_code
    if tool_name is not None:
        attributes["gen_ai.tool.name"] = tool_name
        attributes["gen_ai.operation.name"] = "execute_tool"
    if prompt_name is not None:
        attributes["gen_ai.prompt.name"] = prompt_name
    if mcp_protocol_version is not None:
        attributes["mcp.protocol.version"] = mcp_protocol_version
    _server_operation_duration.record(duration_s, attributes)


def record_server_session_duration(
    duration_s: float,
    *,
    error_type: str | None = None,
    mcp_protocol_version: str | None = None,
) -> None:
    """Record a data point for mcp.server.session.duration."""
    attributes: dict[str, str] = {}
    if error_type is not None:
        attributes["error.type"] = error_type
    if mcp_protocol_version is not None:
        attributes["mcp.protocol.version"] = mcp_protocol_version
    _server_session_duration.record(duration_s, attributes)
