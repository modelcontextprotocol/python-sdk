"""Tests for issue #2057: Requests with "id": null silently misclassified as notifications.

When a JSON-RPC request arrives with ``"id": null``, the SDK should reject it
rather than silently reclassifying it as a ``JSONRPCNotification``.  Both
JSON-RPC 2.0 and the MCP spec restrict request IDs to strings or integers.

See: https://github.com/modelcontextprotocol/python-sdk/issues/2057
"""

import json

import pytest
from pydantic import ValidationError

from mcp.types import (
    JSONRPCNotification,
    jsonrpc_message_adapter,
)


def test_notification_rejects_id_field() -> None:
    """JSONRPCNotification must not accept messages with an 'id' field."""
    with pytest.raises(ValidationError, match="must not include an 'id' field"):
        JSONRPCNotification.model_validate({"jsonrpc": "2.0", "method": "initialize", "id": None})


@pytest.mark.parametrize("id_value", [None, 0, 1, "", "abc"])
def test_notification_rejects_any_id_value(id_value: object) -> None:
    """Notification rejects 'id' regardless of value — null, int, or str."""
    with pytest.raises(ValidationError):
        JSONRPCNotification.model_validate({"jsonrpc": "2.0", "method": "test", "id": id_value})


def test_message_adapter_rejects_null_id() -> None:
    """JSONRPCMessage union must not accept ``"id": null``."""
    raw = {"jsonrpc": "2.0", "method": "initialize", "id": None}
    with pytest.raises(ValidationError):
        jsonrpc_message_adapter.validate_python(raw)


def test_message_adapter_rejects_null_id_json() -> None:
    """Same test but via validate_json (the path used by transports)."""
    raw_json = json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": None})
    with pytest.raises(ValidationError):
        jsonrpc_message_adapter.validate_json(raw_json)
