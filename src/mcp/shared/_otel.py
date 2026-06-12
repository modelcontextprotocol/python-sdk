"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")

# Maps MCP JSON-RPC method names to GenAI semantic convention operation names.
# https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md
_METHOD_TO_GEN_AI_OPERATION: dict[str, str] = {
    "tools/call": "execute_tool",
    "tools/list": "list_tools",
    "resources/read": "read_resource",
    "resources/list": "list_resources",
    "resources/templates/list": "list_resources",
    "prompts/get": "get_prompt",
    "prompts/list": "list_prompts",
}


def build_span_attributes(
    method: str,
    request_id: Any,
    *,
    params: dict[str, Any] | None = None,
    server_name: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build OTel span attributes for an MCP request.

    Produces the base set of semantic convention attributes shared by both
    client (`SpanKind.CLIENT`) and server (`SpanKind.SERVER`) spans.
    Pass `server_name` and `session_id` for server-side spans.
    """
    attrs: dict[str, Any] = {
        "rpc.system": "mcp",
        "mcp.method.name": method,
        "jsonrpc.request.id": str(request_id),
    }

    operation = _METHOD_TO_GEN_AI_OPERATION.get(method)
    if operation is not None:
        attrs["gen_ai.operation.name"] = operation

    if server_name is not None:
        attrs["rpc.service"] = server_name

    if params is not None:
        # gen_ai.tool.name — present on tools/call, prompts/get
        name = params.get("name")
        if isinstance(name, str):
            attrs["gen_ai.tool.name"] = name

        # mcp.resource.uri — present on resources/read; also on completion/complete via ref.uri
        uri: Any = params.get("uri")
        if uri is None:
            ref = params.get("ref")
            if isinstance(ref, dict):
                uri = cast(dict[str, Any], ref).get("uri")
        if uri is not None:
            attrs["mcp.resource.uri"] = str(uri)

    if session_id is not None:
        attrs["mcp.session.id"] = session_id

    return attrs


@contextmanager
def otel_span(
    name: str,
    *,
    kind: SpanKind,
    attributes: dict[str, Any] | None = None,
    context: Context | None = None,
    record_exception: bool = True,
    set_status_on_exception: bool = True,
) -> Iterator[Any]:
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


def extract_trace_context(meta: dict[str, Any]) -> Context | None:
    """Extract W3C trace context from a `_meta` dict.

    Returns `None` when the carrier is malformed; telemetry parsing must
    never fail the request it annotates.
    """
    try:
        return extract(meta)
    except (TypeError, ValueError):
        return None
