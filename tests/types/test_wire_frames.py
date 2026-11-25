"""Snapshot pins for outbound JSON-RPC frames; a diff is a wire-visible change needing a deliberate decision."""

from typing import Any

from inline_snapshot import snapshot
from mcp_types import (
    METHOD_NOT_FOUND,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    ErrorData,
    InputRequiredResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    ListToolsResult,
    ProgressNotification,
    ProgressNotificationParams,
    TextContent,
    Tool,
)
from pydantic import BaseModel


def _body(model: BaseModel) -> dict[str, Any]:
    """Mirror the session layer's outbound payload dump."""
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def _frame(envelope: BaseModel) -> str:
    """Mirror the transports' frame serialization."""
    return envelope.model_dump_json(by_alias=True, exclude_unset=True)


def test_request_frame_carries_the_envelope_and_the_dumped_request_body():
    request = CallToolRequest(params=CallToolRequestParams(name="echo", arguments={"text": "hi"}))
    frame = JSONRPCRequest(jsonrpc="2.0", id=1, **_body(request))
    assert _frame(frame) == snapshot(
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hi"}}}'
    )


def test_notification_frame_has_no_id_and_carries_the_dumped_params():
    notification = ProgressNotification(params=ProgressNotificationParams(progress_token="t1", progress=0.5))
    frame = JSONRPCNotification(jsonrpc="2.0", **_body(notification))
    assert _frame(frame) == snapshot(
        '{"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.5}}'
    )


def test_non_empty_result_dump_carries_result_type_complete_before_the_sieve():
    """The runner's per-version sieve drops `resultType` for pre-2026 peers; the raw dump carries it."""
    result = CallToolResult(content=[TextContent(text="ok")])
    frame = JSONRPCResponse(jsonrpc="2.0", id=1, result=_body(result))
    assert _frame(frame) == snapshot(
        '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}],"isError":false,"resultType":"complete"}}'
    )


def test_cacheable_list_result_dump_carries_default_caching_directives():
    """`ttl_ms`/`cache_scope` default to 0/"private" so the raw dump carries them; the
    runner's per-version sieve drops them for pre-2026 peers."""
    result = ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])
    frame = JSONRPCResponse(jsonrpc="2.0", id=2, result=_body(result))
    assert _frame(frame) == snapshot(
        '{"jsonrpc":"2.0","id":2,"result":{"ttlMs":0,"cacheScope":"private","tools":[{"name":"echo","inputSchema":{"type":"object"}}],"resultType":"complete"}}'
    )


def test_empty_result_frame_dumps_an_empty_result_object():
    """Deployed peers reject extra keys on empty results, so the SDK omits resultType here."""
    frame = JSONRPCResponse(jsonrpc="2.0", id=3, result=_body(EmptyResult()))
    assert _frame(frame) == snapshot('{"jsonrpc":"2.0","id":3,"result":{}}')


def test_input_required_result_frame_carries_the_tag_and_the_embedded_requests():
    result = InputRequiredResult(input_requests={"r1": ListRootsRequest()}, request_state="s1")
    frame = JSONRPCResponse(jsonrpc="2.0", id=4, result=_body(result))
    assert _frame(frame) == snapshot(
        '{"jsonrpc":"2.0","id":4,"result":{"resultType":"input_required","inputRequests":{"r1":{"method":"roots/list"}},"requestState":"s1"}}'
    )


def test_error_frame_wraps_error_data_in_the_jsonrpc_envelope():
    frame = JSONRPCError(jsonrpc="2.0", id=5, error=ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))
    assert _frame(frame) == snapshot('{"jsonrpc":"2.0","id":5,"error":{"code":-32601,"message":"Method not found"}}')
