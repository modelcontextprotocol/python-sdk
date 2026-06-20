"""This module follows the JSON-RPC 2.0 specification: https://www.jsonrpc.org/specification."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, TypeAdapter

RequestId = Annotated[int, Field(strict=True)] | str
"""The ID of a JSON-RPC request."""

JSONRPC_VERSION: Final[Literal["2.0"]] = "2.0"
"""The JSON-RPC version string carried by every MCP message envelope."""


class JSONRPCRequest(BaseModel):
    """A JSON-RPC request that expects a response."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(BaseModel):
    """A JSON-RPC notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """A successful (non-error) response to a request.

    Named `JSONRPCResultResponse` in the 2025-11-25+ schemas; the SDK keeps the original name.
    """

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]


# MCP error codes occupy the JSON-RPC server-error range -32000..-32099.
# Per the 2026-07-28 spec's allocation policy:
#   -32000..-32019  implementation-defined
#   -32020..-32099  reserved for spec-defined codes, allocated sequentially from -32020
#   -32002, -32042  reserved-never-reused (retired by earlier protocol versions)

HEADER_MISMATCH = -32020
"""HTTP headers do not match the request body, or required headers are missing/malformed (protocol 2026-07-28)."""

MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
"""The server requires a client capability the request did not declare (protocol 2026-07-28)."""

UNSUPPORTED_PROTOCOL_VERSION = -32022
"""The request's protocol version is not supported by the server (protocol 2026-07-28)."""

URL_ELICITATION_REQUIRED = -32042
"""A URL-mode elicitation is required before the request can be processed (protocol 2025-11-25 only)."""

# SDK error codes: SDK-internal allocations in the implementation-defined band
# -32000..-32019; not defined by the MCP schema.
CONNECTION_CLOSED = -32000
"""SDK-only: the connection closed before a response arrived; never emitted on the wire."""

REQUEST_TIMEOUT = -32001
"""SDK-only: a request timed out waiting for its response."""

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
"""Standard JSON-RPC: invalid JSON was received."""

INVALID_REQUEST = -32600
"""Standard JSON-RPC: the message is not a valid request object."""

METHOD_NOT_FOUND = -32601
"""Standard JSON-RPC: the requested method does not exist or is not available."""

INVALID_PARAMS = -32602
"""Standard JSON-RPC: invalid method parameters."""

INTERNAL_ERROR = -32603
"""Standard JSON-RPC: an internal error occurred on the receiver.

The SDK uses the generic `ErrorData` envelope; the schema's per-code wrapper types are not constructed.
"""


class ErrorData(BaseModel):
    """Error information for JSON-RPC error responses."""

    code: int
    """The error type that occurred."""

    message: str
    """A short description of the error.

    The message SHOULD be limited to a concise single sentence.
    """

    data: Any = None
    """Additional information about the error.

    The value of this member is defined by the sender (e.g. detailed error information, nested errors, etc.).
    """


class JSONRPCError(BaseModel):
    """A response to a request that indicates an error occurred."""

    jsonrpc: Literal["2.0"]
    id: RequestId | None
    """The id of the request this error responds to.

    Required but nullable per JSON-RPC 2.0: `None` encodes `"id": null` (the id could not be determined).
    """

    error: ErrorData


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
"""Any JSON-RPC envelope that can be decoded off the wire or encoded to be sent."""

jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)
