"""Outbound wire serialization must contain lone-surrogate failures (#3707)."""

import json
import os

import pytest
from mcp_types import (
    INTERNAL_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

from mcp.shared.wire import serialize_jsonrpc_message, serialize_outbound_message


def _surrogate() -> str:
    return os.fsdecode(b"report-\xff.txt")


def test_serialize_jsonrpc_message_rejects_lone_surrogate() -> None:
    message = JSONRPCResponse(jsonrpc="2.0", id=1, result={"text": _surrogate()})
    with pytest.raises(Exception):
        serialize_jsonrpc_message(message)


def test_serialize_outbound_response_with_surrogate_becomes_internal_error() -> None:
    message = JSONRPCResponse(jsonrpc="2.0", id=7, result={"text": _surrogate()})
    wire = serialize_outbound_message(message)
    assert wire is not None
    body = json.loads(wire)
    assert body == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": INTERNAL_ERROR, "message": "Internal server error"},
    }


def test_serialize_outbound_request_with_surrogate_returns_none() -> None:
    message = JSONRPCRequest(
        jsonrpc="2.0",
        id=3,
        method="tools/call",
        params={"name": "echo", "arguments": {"text": _surrogate()}},
    )
    assert serialize_outbound_message(message) is None


def test_serialize_outbound_notification_with_surrogate_returns_none() -> None:
    message = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/message",
        params={"level": "info", "data": _surrogate()},
    )
    assert serialize_outbound_message(message) is None


def test_serialize_outbound_healthy_message_unchanged() -> None:
    message = JSONRPCResponse(jsonrpc="2.0", id=1, result={"ok": True})
    assert serialize_outbound_message(message) == serialize_jsonrpc_message(message)


def test_serialize_outbound_error_with_surrogate_in_message_becomes_internal_error() -> None:
    message = JSONRPCError(jsonrpc="2.0", id=9, error=ErrorData(code=-32000, message=_surrogate()))
    wire = serialize_outbound_message(message)
    assert wire is not None
    body = json.loads(wire)
    assert body["id"] == 9
    assert body["error"]["code"] == INTERNAL_ERROR
    assert body["error"]["message"] == "Internal server error"
