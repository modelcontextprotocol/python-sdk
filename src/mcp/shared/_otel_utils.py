import contextlib
from collections.abc import Iterator
from typing import Any

from opentelemetry.trace import Span, SpanKind, StatusCode, Tracer

from mcp import types
from mcp.shared.exceptions import MCPError

# OTel Semantic Conventions for MCP and GenAI
# See: https://github.com/open-telemetry/semantic-conventions/blob/v1.40.0/docs/gen-ai/mcp.md
MCP_METHOD_NAME = "mcp.method.name"
MCP_RESOURCE_URI = "mcp.resource.uri"
JSONRPC_REQUEST_ID = "jsonrpc.request.id"

GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROMPT_NAME = "gen_ai.prompt.name"

ERROR_TYPE = "error.type"
RPC_RESPONSE_STATUS_CODE = "rpc.response.status_code"


def _get_span_name(
    request: types.ClientRequest | types.ServerRequest | types.ClientNotification | types.ServerNotification,
) -> str:
    """Computes the span name based on the request type and parameters."""
    target = None
    match request:
        case types.CallToolRequest():
            target = request.params.name
        case types.GetPromptRequest():
            target = request.params.name
        case _:
            pass

    if target:
        return f"{request.method} {target}"
    return request.method


def _get_common_attributes(
    request: types.ClientRequest | types.ServerRequest | types.ClientNotification | types.ServerNotification,
    *,
    json_rpc_request_id: int | str | None = None,
) -> dict[str, Any]:
    """Computes common attributes for both client and server spans."""
    attributes = {MCP_METHOD_NAME: request.method}

    if json_rpc_request_id is not None:
        attributes[JSONRPC_REQUEST_ID] = str(json_rpc_request_id)

    match request:
        case types.CallToolRequest():
            attributes[GEN_AI_TOOL_NAME] = request.params.name
            attributes[GEN_AI_OPERATION_NAME] = "execute_tool"
        case types.GetPromptRequest():
            attributes[GEN_AI_PROMPT_NAME] = request.params.name
        case (
            types.ReadResourceRequest()
            | types.SubscribeRequest()
            | types.UnsubscribeRequest()
            | types.ResourceUpdatedNotification()
        ):
            attributes[MCP_RESOURCE_URI] = request.params.uri
        case _:
            pass
    return attributes


_ERROR_NAMES = {
    types.INVALID_PARAMS: "invalid_params",
    types.METHOD_NOT_FOUND: "method_not_found",
    types.CONNECTION_CLOSED: "connection_closed",
    types.REQUEST_TIMEOUT: "timeout",
    types.PARSE_ERROR: "parse_error",
    types.INTERNAL_ERROR: "internal_error",
    types.INVALID_REQUEST: "invalid_request",
    types.URL_ELICITATION_REQUIRED: "url_elicitation_required",
}


def _record_error_data(span: Span, e: types.ErrorData, record_status: bool = True) -> None:
    """Record an MCP protocol error on the span set status

    https://github.com/open-telemetry/semantic-conventions/blob/v1.40.0/docs/general/recording-errors.md
    """
    if not span.is_recording():
        return

    span.set_attribute(ERROR_TYPE, _ERROR_NAMES.get(e.code, str(e.code)))
    span.set_attribute(RPC_RESPONSE_STATUS_CODE, str(e.code))
    span.set_status(status=StatusCode.ERROR, description=e.message)


@contextlib.contextmanager
def mcp_client_span(
    tracer: Tracer,
    request: types.ClientRequest | types.ServerRequest | types.ClientNotification | types.ServerNotification,
    *,
    json_rpc_request_id: int | str | None = None,
) -> Iterator[Span]:
    """Starts an MCP client span as current span

    https://github.com/open-telemetry/semantic-conventions/blob/v1.40.0/docs/gen-ai/mcp.md#client
    """
    span_name = _get_span_name(request)
    attributes = _get_common_attributes(request, json_rpc_request_id=json_rpc_request_id)

    reraise_exc = None
    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.CLIENT,
        attributes=attributes,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except MCPError as mcp_error:
            _record_error_data(span, mcp_error.error)
            span.record_exception(mcp_error)
            # re-raise outside of with block to avoid overwriting span status
            reraise_exc = mcp_error

    if reraise_exc:
        raise reraise_exc
