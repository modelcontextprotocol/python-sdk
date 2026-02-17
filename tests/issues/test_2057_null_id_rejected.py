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
    JSONRPCRequest,
    jsonrpc_message_adapter,
)


class TestNullIdRejection:
    """Verify that ``"id": null`` is never silently absorbed."""

    def test_request_rejects_null_id(self) -> None:
        """JSONRPCRequest correctly rejects null id."""
        with pytest.raises(ValidationError):
            JSONRPCRequest.model_validate(
                {"jsonrpc": "2.0", "method": "initialize", "id": None}
            )

    def test_notification_rejects_id_field(self) -> None:
        """JSONRPCNotification must not accept messages with an 'id' field."""
        with pytest.raises(ValidationError, match="must not include an 'id' field"):
            JSONRPCNotification.model_validate(
                {"jsonrpc": "2.0", "method": "initialize", "id": None}
            )

    def test_notification_rejects_any_id_value(self) -> None:
        """Notification rejects 'id' regardless of value — null, int, or str."""
        for id_value in [None, 0, 1, "", "abc"]:
            with pytest.raises(ValidationError):
                JSONRPCNotification.model_validate(
                    {"jsonrpc": "2.0", "method": "test", "id": id_value}
                )

    def test_message_adapter_rejects_null_id(self) -> None:
        """JSONRPCMessage union must not accept ``"id": null``."""
        raw = {"jsonrpc": "2.0", "method": "initialize", "id": None}
        with pytest.raises(ValidationError):
            jsonrpc_message_adapter.validate_python(raw)

    def test_message_adapter_rejects_null_id_json(self) -> None:
        """Same test but via validate_json (the path used by transports)."""
        raw_json = json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": None})
        with pytest.raises(ValidationError):
            jsonrpc_message_adapter.validate_json(raw_json)

    def test_valid_notification_still_works(self) -> None:
        """A valid notification (no 'id' field at all) must still parse fine."""
        msg = JSONRPCNotification.model_validate(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert msg.method == "notifications/initialized"

    def test_valid_notification_with_params(self) -> None:
        """Notification with params but no 'id' should work."""
        msg = JSONRPCNotification.model_validate(
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 50}}
        )
        assert msg.method == "notifications/progress"
        assert msg.params == {"progress": 50}

    def test_valid_request_with_string_id(self) -> None:
        """A valid request with a string id still works."""
        msg = JSONRPCRequest.model_validate(
            {"jsonrpc": "2.0", "method": "initialize", "id": "abc-123"}
        )
        assert msg.id == "abc-123"

    def test_valid_request_with_int_id(self) -> None:
        """A valid request with an integer id still works."""
        msg = JSONRPCRequest.model_validate(
            {"jsonrpc": "2.0", "method": "initialize", "id": 42}
        )
        assert msg.id == 42

    def test_message_adapter_parses_valid_request(self) -> None:
        """The union adapter correctly identifies a valid request."""
        raw = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        parsed = jsonrpc_message_adapter.validate_python(raw)
        assert isinstance(parsed, JSONRPCRequest)
        assert parsed.id == 1

    def test_message_adapter_parses_valid_notification(self) -> None:
        """The union adapter correctly identifies a valid notification."""
        raw = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        parsed = jsonrpc_message_adapter.validate_python(raw)
        assert isinstance(parsed, JSONRPCNotification)
        assert parsed.method == "notifications/initialized"

    def test_message_adapter_parses_notification_json(self) -> None:
        """The union adapter correctly identifies a valid notification via JSON."""
        raw_json = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        parsed = jsonrpc_message_adapter.validate_json(raw_json)
        assert isinstance(parsed, JSONRPCNotification)
