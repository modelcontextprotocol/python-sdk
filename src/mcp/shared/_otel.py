"""OpenTelemetry helpers for MCP."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, get_tracer

_tracer = get_tracer("mcp-python-sdk")


def build_span_attributes(
    method: str,
    request_id: Any,
    *,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build OTel span attributes for an MCP request.

    Produces the base set of semantic convention attributes shared by both
    client (`SpanKind.CLIENT`) and server (`SpanKind.SERVER`) spans.

    Per the GenAI MCP semconv spec, `gen_ai.operation.name` SHOULD be set to
    `execute_tool` for `tools/call` and SHOULD NOT be set for other methods.
    https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/mcp.md
    """
    attrs: dict[str, Any] = {
        "rpc.system": "mcp",
        "mcp.method.name": method,
        "jsonrpc.request.id": str(request_id),
    }

    if params is not None:
        if method == "tools/call":
            # gen_ai.operation.name SHOULD be set to execute_tool for tools/call only.
            attrs["gen_ai.operation.name"] = "execute_tool"
            name = params.get("name")
            if isinstance(name, str):
                attrs["gen_ai.tool.name"] = name

        elif method == "prompts/get":
            name = params.get("name")
            if isinstance(name, str):
                attrs["gen_ai.prompt.name"] = name

        # mcp.resource.uri — resources/read, resources/subscribe, resources/unsubscribe,
        # notifications/resources/updated, and completion/complete via ref.uri
        uri: Any = params.get("uri")
        if uri is None:
            ref = params.get("ref")
            if isinstance(ref, dict):
                uri = cast(dict[str, Any], ref).get("uri")
        if uri is not None:
            attrs["mcp.resource.uri"] = str(uri)

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
