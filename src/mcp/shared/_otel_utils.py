import contextlib
from collections.abc import Iterator

from opentelemetry.trace import Span, SpanKind, Tracer

from mcp import types
from mcp.shared.exceptions import MCPError


@contextlib.contextmanager
def mcp_client_span(
    tracer: Tracer,
    request: types.ClientRequest | types.ServerRequest | types.ClientNotification | types.ServerNotification,
    *,
    json_rpc_request_id: int | None = None,
) -> Iterator[Span]:
    """Starts an MCP client span as current span

    https://github.com/open-telemetry/semantic-conventions/blob/v1.40.0/docs/gen-ai/mcp.md#client
    """
    attributes = {"mcp.method.name": request.method}

    # When omitted, the request is treated as a notification. Instrumentations SHOULD NOT
    # capture this attribute when the id is null or omitted.
    if json_rpc_request_id is not None:
        attributes["jsonrpc.request.id"] = str(json_rpc_request_id)

    target = None

    match request:
        case types.CallToolRequest():
            target = request.params.name
            attributes["gen_ai.tool.name"] = target
            attributes["gen_ai.operation.name"] = "execute_tool"
        case types.GetPromptRequest():
            target = request.params.name
            attributes["gen_ai.prompt.name"] = target
        case (
            types.ReadResourceRequest()
            | types.SubscribeRequest()
            | types.UnsubscribeRequest()
            | types.ResourceUpdatedNotification()
        ):
            attributes["mcp.resource.uri"] = request.params.uri
        case _:
            pass

    if target:
        span_name = f"{request.method} {target}"
    else:
        span_name = request.method

    with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT, attributes=attributes) as span:
        try:
            yield span
        except MCPError as e:
            if span.is_recording():
                if e.code == types.REQUEST_TIMEOUT:
                    span.set_attribute("error.type", "timeout")
                else:
                    span.set_attribute("error.type", str(e.code))
                    span.set_attribute("rpc.response.status_code", str(e.code))
            raise
