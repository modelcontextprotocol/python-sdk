"""This module follows the JSON-RPC 2.0 specification: https://www.jsonrpc.org/specification."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

RequestId = Annotated[int, Field(strict=True)] | str
"""The ID of a JSON-RPC request."""


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


# TODO(Marcelo): This is actually not correct. A JSONRPCResponse is the union of a successful response and an error.
class JSONRPCResponse(BaseModel):
    """A successful (non-error) response to a request."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]


# MCP-specific error codes in the range [-32000, -32099]
URL_ELICITATION_REQUIRED = -32042
"""Error code indicating that a URL mode elicitation is required before the request can be processed."""

# SDK error codes
CONNECTION_CLOSED = -32000
REQUEST_TIMEOUT = -32001

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ErrorData(BaseModel):
    """Error information for JSON-RPC error responses."""

    code: int
    """The error type that occurred."""

    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single
    sentence.
    """

    data: Any = None
    """
    Additional information about the error. The value of this member is defined by the
    sender (e.g. detailed error information, nested errors etc.).
    """


class JSONRPCError(BaseModel):
    """A response to a request that indicates an error occurred."""

    jsonrpc: Literal["2.0"]
    id: str | int
    error: ErrorData


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)
