"""
Tests for JSON-RPC TypeAdapter message discrimination.

The core question: Given a raw JSON dict, does the TypeAdapter correctly
identify whether it's a Request, Notification, ResultResponse, or ErrorResponse?

Discrimination is based on field presence:
- Request:        has 'id' AND 'method'
- Notification:   has 'method' but NO 'id'
- ResultResponse: has 'id' AND 'result' (no 'method')
- ErrorResponse:  has 'error' field
"""

from typing import Any

import pytest

from mcp_v2.types.json_rpc import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JSONRPCErrorResponse,
    JSONRPCMessage,
    JSONRPCMessageAdapter,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResultResponse,
)


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        # Requests: 'id' + 'method'
        ({"jsonrpc": "2.0", "id": 1, "method": "ping"}, JSONRPCRequest),
        ({"jsonrpc": "2.0", "id": "str-id", "method": "tools/call", "params": {"x": 1}}, JSONRPCRequest),
        # Notifications: 'method', no 'id'
        ({"jsonrpc": "2.0", "method": "notifications/initialized"}, JSONRPCNotification),
        ({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}, JSONRPCNotification),
        # Result responses: 'id' + 'result', no 'method'
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, JSONRPCResultResponse),
        ({"jsonrpc": "2.0", "id": "abc", "result": {"data": 123}}, JSONRPCResultResponse),
        # Error responses: has 'error'
        (
            {"jsonrpc": "2.0", "id": 1, "error": {"code": INVALID_REQUEST, "message": "Invalid Request"}},
            JSONRPCErrorResponse,
        ),
        (
            {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}},
            JSONRPCErrorResponse,
        ),
    ],
)
def test_adapter_returns_correct_type(raw: dict[str, Any], expected_type: type[JSONRPCMessage]) -> None:
    """TypeAdapter should discriminate message types based on field presence."""
    message = JSONRPCMessageAdapter.validate_python(raw)
    assert isinstance(message, expected_type)
