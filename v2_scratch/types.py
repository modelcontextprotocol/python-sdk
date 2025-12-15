"""
V2 Types - Cleaner type definitions for the new lowlevel API.

Key differences from v1:
- Result types inherit from JSONRPCResultResponse (include jsonrpc, id) - can be sent directly
- Notification types inherit from JSONRPCNotification (include jsonrpc) - can be sent directly
- Handler returns result with id from request.id, no wrapping needed

Type naming follows the MCP spec (2025-11-25):
- JSONRPCResultResponse: successful response with result data
- JSONRPCErrorResponse: error response with error data
- JSONRPCResponse: union of the above (type alias, not a class)
- JSONRPCMessage: Request | Notification | Response (includes errors)
"""

from typing import Any, Literal

from pydantic import BaseModel

RequestId = str | int


class JSONRPCBase(BaseModel):
    """Base class for all JSON-RPC messages."""

    jsonrpc: Literal["2.0"] = "2.0"


class JSONRPCRequest(JSONRPCBase):
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(JSONRPCBase):
    method: str
    params: dict[str, Any] | None = None


class ErrorData(BaseModel):
    """Error information in a JSON-RPC error response."""

    code: int
    message: str
    data: Any | None = None


class JSONRPCResultResponse(JSONRPCBase):
    """A successful (non-error) response to a request."""

    id: RequestId


class JSONRPCErrorResponse(JSONRPCBase):
    """A response to a request that indicates an error occurred."""

    id: RequestId | None = None
    error: ErrorData


# Type alias per spec: a response is either a result or an error
JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse

# Message union - includes errors via JSONRPCResponse
JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse


# Typed result classes - handler uses request.id
class InitializeResult(JSONRPCResultResponse):
    protocolVersion: str
    capabilities: dict[str, Any]
    serverInfo: dict[str, Any]


class CallToolResult(JSONRPCResultResponse):
    content: list[dict[str, Any]]
    isError: bool = False


class ListToolsResult(JSONRPCResultResponse):
    tools: list[dict[str, Any]]


class ListPromptsResult(JSONRPCResultResponse):
    prompts: list[dict[str, Any]]


class ListResourcesResult(JSONRPCResultResponse):
    resources: list[dict[str, Any]]


# Method name literals for type-safe handler registration
RequestMethod = Literal[
    "initialize",
    "ping",
    "tools/call",
    "tools/list",
    "prompts/get",
    "prompts/list",
    "resources/read",
    "resources/list",
    "resources/templates/list",
    "completion/complete",
    "logging/setLevel",
]

# Notifications the client sends to server (server handles these)
ClientNotificationMethod = Literal[
    "notifications/initialized",
    "notifications/cancelled",
    "notifications/roots/list_changed",
]

# Notifications the server sends to client (for send_notification)
ServerNotificationMethod = Literal[
    "notifications/progress",
    "notifications/message",
    "notifications/resources/updated",
    "notifications/resources/list_changed",
    "notifications/tools/list_changed",
    "notifications/prompts/list_changed",
]


# Notification params as BaseModels with method discriminator
class ProgressNotificationParams(BaseModel):
    method: Literal["notifications/progress"] = "notifications/progress"
    progressToken: str
    progress: float
    total: float | None = None


class LogNotificationParams(BaseModel):
    method: Literal["notifications/message"] = "notifications/message"
    level: str
    data: str
    logger: str | None = None


class ResourceUpdatedNotificationParams(BaseModel):
    method: Literal["notifications/resources/updated"] = "notifications/resources/updated"
    uri: str


NotificationParams = ProgressNotificationParams | LogNotificationParams | ResourceUpdatedNotificationParams
