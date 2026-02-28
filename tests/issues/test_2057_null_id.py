"""Test for issue #2057: Requests with "id": null silently misclassified as notifications."""

import pytest
from pydantic import ValidationError

from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, jsonrpc_message_adapter


class TestNullIdRejection:
    """Verify that JSON-RPC messages with id: null are rejected."""

    def test_request_rejects_null_id(self):
        """JSONRPCRequest should reject id: null."""
        with pytest.raises(ValidationError):
            JSONRPCRequest.model_validate(
                {"jsonrpc": "2.0", "method": "initialize", "id": None}
            )

    def test_notification_rejects_extra_id_field(self):
        """JSONRPCNotification should not absorb an extra 'id' field."""
        with pytest.raises(ValidationError):
            JSONRPCNotification.model_validate(
                {"jsonrpc": "2.0", "method": "initialize", "id": None}
            )

    def test_message_adapter_rejects_null_id(self):
        """The union adapter should reject messages with id: null entirely."""
        with pytest.raises(ValidationError):
            jsonrpc_message_adapter.validate_python(
                {"jsonrpc": "2.0", "method": "initialize", "id": None}
            )

    def test_valid_notification_without_id(self):
        """A proper notification (no id field) should still validate."""
        msg = jsonrpc_message_adapter.validate_python(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert isinstance(msg, JSONRPCNotification)

    def test_valid_request_with_int_id(self):
        """A proper request with an integer id should still validate."""
        msg = jsonrpc_message_adapter.validate_python(
            {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        )
        assert isinstance(msg, JSONRPCRequest)

    def test_valid_request_with_string_id(self):
        """A proper request with a string id should still validate."""
        msg = jsonrpc_message_adapter.validate_python(
            {"jsonrpc": "2.0", "method": "initialize", "id": "abc-123"}
        )
        assert isinstance(msg, JSONRPCRequest)
