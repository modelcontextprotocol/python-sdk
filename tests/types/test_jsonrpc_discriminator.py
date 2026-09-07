"""Behavior pins for the key-presence discriminator on `jsonrpc_message_adapter`.

The adapter validates exactly one union branch chosen by
`_discriminate_jsonrpc_message`; these tests pin classification parity with the
previous smart-union behavior, including the degenerate shapes.
"""

import json
from typing import Any

import pytest
from mcp_types import (
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)
from pydantic import ValidationError

REQUEST_WIRE: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
NOTIFICATION_WIRE: dict[str, Any] = {"jsonrpc": "2.0", "method": "notifications/progress"}
RESPONSE_WIRE: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
ERROR_WIRE: dict[str, Any] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}


@pytest.mark.parametrize(
    ("wire", "expected_type"),
    [
        (REQUEST_WIRE, JSONRPCRequest),
        (NOTIFICATION_WIRE, JSONRPCNotification),
        (RESPONSE_WIRE, JSONRPCResponse),
        (ERROR_WIRE, JSONRPCError),
    ],
)
def test_validate_json_classifies_each_variant(wire: dict[str, object], expected_type: type) -> None:
    message = jsonrpc_message_adapter.validate_json(json.dumps(wire), by_name=False)
    assert type(message) is expected_type


@pytest.mark.parametrize("bad_id", [None, 1.5, True])
def test_method_with_non_request_id_is_a_notification(bad_id: object) -> None:
    """A `method` member with a null/float/bool id downgrades to a notification (smart-union parity)."""
    wire = {"jsonrpc": "2.0", "id": bad_id, "method": "m"}
    message = jsonrpc_message_adapter.validate_python(wire, by_name=False)
    assert type(message) is JSONRPCNotification


def test_method_with_string_id_is_a_request() -> None:
    message = jsonrpc_message_adapter.validate_python({"jsonrpc": "2.0", "id": "abc", "method": "m"}, by_name=False)
    assert type(message) is JSONRPCRequest


def test_method_wins_over_result() -> None:
    """A degenerate {method, id, result} object classifies as a request (smart-union parity)."""
    wire: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "m", "result": {}}
    message = jsonrpc_message_adapter.validate_python(wire, by_name=False)
    assert type(message) is JSONRPCRequest


def test_error_wins_over_result() -> None:
    """A degenerate {id, result, error} object classifies as an error (smart-union parity)."""
    wire = {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -32603, "message": "boom"}}
    message = jsonrpc_message_adapter.validate_python(wire, by_name=False)
    assert type(message) is JSONRPCError


@pytest.mark.parametrize(
    ("request_id", "expected_type"),
    [
        (1, JSONRPCRequest),
        (None, JSONRPCNotification),
    ],
)
def test_method_wins_over_error(request_id: object, expected_type: type) -> None:
    """A spec-invalid {method, error} hybrid classifies as a call, deliberately diverging from smart union.

    Smart-union scoring preferred `JSONRPCError` here (more matching fields),
    which let a malformed frame masquerade as an error response to a pending
    request. The `method` key now deterministically makes the message a call.
    """
    wire: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": "m", "error": {"code": -1, "message": "x"}}
    message = jsonrpc_message_adapter.validate_python(wire, by_name=False)
    assert type(message) is expected_type


def test_non_string_method_with_result_is_rejected() -> None:
    """A `method` key selects the call arm even when its value is invalid, deliberately diverging from smart union.

    Smart union previously fell through to `JSONRPCResponse` for
    {method: 123, result: {}}; the call arm now rejects the non-string method.
    """
    wire: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": 123, "result": {}}
    with pytest.raises(ValidationError) as exc_info:
        jsonrpc_message_adapter.validate_python(wire, by_name=False)
    assert exc_info.value.errors()[0]["loc"] == ("request", "method")


@pytest.mark.parametrize(
    "unclassifiable",
    [
        b'{"foo": 1}',
        b"[]",
    ],
)
def test_unclassifiable_json_raises_single_tagged_error(unclassifiable: bytes) -> None:
    with pytest.raises(ValidationError) as exc_info:
        jsonrpc_message_adapter.validate_json(unclassifiable, by_name=False)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["type"] == "jsonrpc_message_invalid"


def test_unclassifiable_python_scalar_raises_tagged_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        jsonrpc_message_adapter.validate_python(42, by_name=False)
    assert exc_info.value.errors()[0]["type"] == "jsonrpc_message_invalid"


def test_chosen_branch_failure_reports_single_branch_location() -> None:
    """Once tagged, only the chosen branch validates; its errors carry the tag as the location root."""
    wire = {"jsonrpc": "2.0", "id": 1, "method": "m", "params": "notadict"}
    with pytest.raises(ValidationError) as exc_info:
        jsonrpc_message_adapter.validate_python(wire, by_name=False)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("request", "params")


@pytest.mark.parametrize(
    "instance",
    [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list"),
        JSONRPCNotification(jsonrpc="2.0", method="notifications/progress"),
        JSONRPCResponse(jsonrpc="2.0", id=1, result={"tools": []}),
        JSONRPCError(jsonrpc="2.0", id=None, error=ErrorData(code=-32700, message="Parse error")),
    ],
)
def test_model_instances_revalidate_and_dump_identically(instance: JSONRPCMessage) -> None:
    """The discriminator also tags already-constructed models (revalidation and dump paths)."""
    revalidated = jsonrpc_message_adapter.validate_python(instance, by_name=False)
    assert revalidated is instance
    assert (
        jsonrpc_message_adapter.dump_json(instance, by_alias=True, exclude_none=True)
        == instance.model_dump_json(by_alias=True, exclude_none=True).encode()
    )
