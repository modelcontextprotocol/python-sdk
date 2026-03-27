from importlib import import_module
from typing import TYPE_CHECKING, Any

from .client.client import Client
from .client.session import ClientSession
from .server.session import ServerSession
from .server.stdio import stdio_server
from .shared.exceptions import MCPError, UrlElicitationRequiredError
from .types import (
    CallToolRequest,
    ClientCapabilities,
    ClientNotification,
    ClientRequest,
    ClientResult,
    CompleteRequest,
    CreateMessageRequest,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ErrorData,
    GetPromptRequest,
    GetPromptResult,
    Implementation,
    IncludeContext,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsResult,
    LoggingLevel,
    LoggingMessageNotification,
    Notification,
    PingRequest,
    ProgressNotification,
    PromptsCapability,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourcesCapability,
    ResourceUpdatedNotification,
    RootsCapability,
    SamplingCapability,
    SamplingContent,
    SamplingContextCapability,
    SamplingMessage,
    SamplingMessageContentBlock,
    SamplingToolsCapability,
    ServerCapabilities,
    ServerNotification,
    ServerRequest,
    ServerResult,
    SetLevelRequest,
    StopReason,
    SubscribeRequest,
    Tool,
    ToolChoice,
    ToolResultContent,
    ToolsCapability,
    ToolUseContent,
    UnsubscribeRequest,
)
from .types import Role as SamplingRole

if TYPE_CHECKING:
    from .client.session_group import ClientSessionGroup
    from .client.stdio import StdioServerParameters, stdio_client

__all__ = [
    "CallToolRequest",
    "Client",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "ClientSession",
    "ClientSessionGroup",
    "CompleteRequest",
    "CreateMessageRequest",
    "CreateMessageResult",
    "CreateMessageResultWithTools",
    "ErrorData",
    "GetPromptRequest",
    "GetPromptResult",
    "Implementation",
    "IncludeContext",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCError",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "MCPError",
    "Notification",
    "PingRequest",
    "ProgressNotification",
    "PromptsCapability",
    "ReadResourceRequest",
    "ReadResourceResult",
    "Resource",
    "ResourcesCapability",
    "ResourceUpdatedNotification",
    "RootsCapability",
    "SamplingCapability",
    "SamplingContent",
    "SamplingContextCapability",
    "SamplingMessage",
    "SamplingMessageContentBlock",
    "SamplingRole",
    "SamplingToolsCapability",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "ServerSession",
    "SetLevelRequest",
    "StdioServerParameters",
    "StopReason",
    "SubscribeRequest",
    "Tool",
    "ToolChoice",
    "ToolResultContent",
    "ToolsCapability",
    "ToolUseContent",
    "UnsubscribeRequest",
    "UrlElicitationRequiredError",
    "stdio_client",
    "stdio_server",
]

_LAZY_EXPORTS = {
    "ClientSessionGroup": (".client.session_group", "ClientSessionGroup"),
    "StdioServerParameters": (".client.stdio", "StdioServerParameters"),
    "stdio_client": (".client.stdio", "stdio_client"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, export_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), export_name)
    globals()[name] = value
    return value
