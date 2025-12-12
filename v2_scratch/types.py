"""
V2 Types - Cleaner type definitions for the new lowlevel API.

Key differences from v1:
- Result types inherit from JSONRPCResponse (include jsonrpc, id) - can be sent directly
- Notification types inherit from JSONRPCNotification (include jsonrpc) - can be sent directly
- Handler returns result with id from request.id, no wrapping needed
"""

from typing import Any, Literal

from pydantic import  BaseModel


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


class JSONRPCError(JSONRPCBase):
    id: RequestId | None
    error: dict[str, Any]


class JSONRPCResponse(JSONRPCBase):
    """Base for responses - handlers return subclasses of this."""
    id: RequestId


# Typed result classes - handler uses request.id
class InitializeResult(JSONRPCResponse):
    protocolVersion: str
    capabilities: dict[str, Any]
    serverInfo: dict[str, Any]


class CallToolResult(JSONRPCResponse):
    content: list[dict[str, Any]]
    isError: bool = False


class ListToolsResult(JSONRPCResponse):
    tools: list[dict[str, Any]]


class ListPromptsResult(JSONRPCResponse):
    prompts: list[dict[str, Any]]


class ListResourcesResult(JSONRPCResponse):
    resources: list[dict[str, Any]]


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError


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
