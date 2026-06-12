"""This module follows the JSON-RPC 2.0 specification: https://www.jsonrpc.org/specification.

The ``# M-2 alternative:`` comment below follows the decision-marker
convention described in the ``mcp.types._types`` module docstring: it names a
reviewed design alternative that was NOT taken, as a record, not a TODO.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, Field, TypeAdapter

RequestId = Annotated[int, Field(strict=True)] | str
"""A uniquely identifying ID for a request in JSON-RPC.

Identical in every supported protocol version: a string or an integer (the JSON
form of every schema version pins the numeric kind to integer; null is never
allowed). The strict ``int`` arm disables pydantic cross-coercion so a parsed id
keeps the exact wire type the peer sent (``"7"`` stays ``str``; ``True`` is
rejected), which is what lets a response echo the id back unchanged.
"""

JSONRPC_VERSION: Final[Literal["2.0"]] = "2.0"
"""The JSON-RPC protocol version carried by every MCP message envelope.

Identical in every MCP protocol version (2024-11-05 through 2026-07-28): the
``jsonrpc`` field of every envelope type is ``Literal["2.0"]`` and always holds
exactly this value.
"""


class JSONRPCRequest(BaseModel):
    """A JSON-RPC request that expects a response."""

    jsonrpc: Literal["2.0"]
    """The JSON-RPC protocol version. Always "2.0"."""

    id: RequestId
    """A uniquely identifying ID for this request, established by the sender."""

    method: str
    """The name of the method being invoked."""

    params: dict[str, Any] | None = None
    """The parameter object for the method, if any."""


class JSONRPCNotification(BaseModel):
    """A JSON-RPC notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    """The JSON-RPC protocol version. Always "2.0"."""

    method: str
    """The method name of the notification."""

    params: dict[str, Any] | None = None
    """The notification's parameters as an untyped mapping.

    Typed access goes through the `Notification` payload models in `mcp.types`;
    the envelope deliberately leaves this untyped.
    """


class JSONRPCResponse(BaseModel):
    """A successful (non-error) response to a request.

    Wire shape is identical across all supported protocol versions. The spec named
    this type ``JSONRPCResponse`` through 2025-06-18 and renamed it
    ``JSONRPCResultResponse`` in 2025-11-25 (recycling ``JSONRPCResponse`` for the
    success|error union); the SDK keeps its original name, recorded in the
    spec-name divergence map.
    """

    jsonrpc: Literal["2.0"]
    """The JSON-RPC protocol version. Always "2.0"."""

    id: RequestId
    """The id of the request this response answers."""

    result: dict[str, Any]
    """The result payload as a raw JSON object.

    The envelope deliberately leaves the payload untyped: typed result models are
    validated and serialized at the session layer, then wrapped in this envelope.
    """


# MCP-specific error codes in the range [-32000, -32099]
URL_ELICITATION_REQUIRED = -32042
"""Error code indicating that a URL mode elicitation is required before the request can be processed.

Removed in protocol 2026-07-28; used on 2025-11-25 sessions (the 2026-07-28
input-required flow delivers URL elicitations inside results instead).
"""

MISSING_REQUIRED_CLIENT_CAPABILITY = -32003
"""Error code returned when a server requires a client capability that was
not declared in the request's `clientCapabilities` (protocol 2026-07-28).

The error's `data.requiredCapabilities` lists the missing capabilities; see
`MissingRequiredClientCapabilityErrorData` in `mcp.types`. For HTTP, the
response status code MUST be 400 Bad Request.
"""

UNSUPPORTED_PROTOCOL_VERSION = -32004
"""Error code returned when the request's protocol version is not supported by the server.

Introduced in protocol 2026-07-28: returned when the version a request claims (the
``io.modelcontextprotocol/protocolVersion`` ``_meta`` key, which must match the HTTP
``MCP-Protocol-Version`` header) is unknown to the server or unsupported. For HTTP,
the response status code MUST be ``400 Bad Request``. The error's ``data`` member
carries an ``UnsupportedProtocolVersionErrorData`` payload listing the versions the
server supports, so the client can retry with a mutually supported one.
"""

# SDK error codes
CONNECTION_CLOSED = -32000
REQUEST_TIMEOUT = -32001
REQUEST_CANCELLED = -32002

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
"""Standard JSON-RPC error code: invalid JSON was received.

Returned when the receiver cannot parse the JSON text of a message. The
2026-07-28 schema also publishes a typed ``ParseError`` error-object shape for
this code; the SDK deliberately keeps the generic ``ErrorData`` envelope and
represents a parse error as ``ErrorData(code=PARSE_ERROR, message=...)``.
"""

INVALID_REQUEST = -32600
"""Standard JSON-RPC error code: the message is not a valid request object.

Returned when a message's structure does not conform to the JSON-RPC 2.0
specification requirements for a request (e.g. missing required fields like
``jsonrpc`` or ``method``, or invalid types for those fields).
"""

METHOD_NOT_FOUND = -32601
"""Error code: the requested method does not exist or is not available.

Since protocol 2026-07-28 this explicitly includes methods gated behind a
server capability the server did not advertise; a request that requires a
CLIENT capability the client did not declare is signalled by code -32003
(``MISSING_REQUIRED_CLIENT_CAPABILITY``) instead.
"""

INVALID_PARAMS = -32602
"""Standard JSON-RPC error code: the method parameters are invalid or malformed."""

INTERNAL_ERROR = -32603
"""Standard JSON-RPC error code: an internal error occurred on the receiver.

Returned when the receiver encounters an unexpected condition that prevents
it from fulfilling the request. Identical in every MCP protocol version
(2024-11-05 through 2026-07-28). The 2026-07-28 schema's ``InternalError``
wrapper interface is deliberately not modeled: error responses use the
generic ``ErrorData`` envelope, and ``ErrorData.code`` carries this value.
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
    """The JSON-RPC protocol version. Always "2.0"."""

    # M-2 alternative: id gains "= None" — 2025-11-25 and later schemas also allow omitting the member.
    id: RequestId | None
    """The id of the request this error responds to.

    ``None`` is the JSON-RPC 2.0 ``"id": null`` form, used when no request id
    could be determined (e.g. a parse error). The member itself is always present
    on the wire; SDK-generated error responses always set an id.
    """

    error: ErrorData
    """The error that occurred."""


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
"""Any valid JSON-RPC object that can be decoded off the wire, or encoded to be sent.

One envelope for every protocol version: the 2025-11-25 schema restructure
(`JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse`) changed the
schema's union nesting and member names, not the wire shape of a frame. The
2025-03-26 batch frames (JSON arrays of messages) are not members and are not
supported.
"""

jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)
"""TypeAdapter for parsing wire frames into JSONRPCMessage at the transport boundary."""
