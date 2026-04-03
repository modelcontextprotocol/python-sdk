"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")
MCP_RPC_SYSTEM = "mcp"


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


def build_client_span_attributes(
    *,
    method: str,
    request_id: str | int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build OTel attributes for an MCP client request span."""
    attributes: dict[str, Any] = {
        "rpc.system": MCP_RPC_SYSTEM,
        "rpc.method": method,
        "mcp.method.name": method,
        "jsonrpc.request.id": request_id,
    }

    if params is not None and (resource_uri := params.get("uri")) is not None:
        attributes["mcp.resource.uri"] = resource_uri

    return attributes


def build_server_span_attributes(
    *,
    service_name: str,
    method: str,
    request_id: str | int,
    params: Any = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build OTel attributes for an MCP server request span."""
    attributes: dict[str, Any] = {
        "rpc.system": MCP_RPC_SYSTEM,
        "rpc.service": service_name,
        "rpc.method": method,
        "mcp.method.name": method,
        "jsonrpc.request.id": request_id,
    }

    resource_uri = getattr(params, "uri", None)
    if resource_uri is not None:
        attributes["mcp.resource.uri"] = str(resource_uri)

    if session_id is not None:
        attributes["mcp.session.id"] = session_id

    return attributes
