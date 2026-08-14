from importlib import import_module
from typing import TYPE_CHECKING

from mcp_types import (
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
from mcp_types import Role as SamplingRole

from .shared.exceptions import MCPDeprecationWarning, MCPError, UrlElicitationRequiredError
from .shared.uri_template import InvalidUriTemplate, UriTemplate

# The client/server names and the `mcp.types` submodule are bound lazily on
# first access (PEP 562), so `import mcp` no longer imports the client and
# server stacks; type checkers see the same names through the block below.
_LAZY = {  # name -> the module it is imported from
    "Client": "mcp.client.client",
    "ClientSession": "mcp.client.session",
    "ClientSessionGroup": "mcp.client.session_group",
    "InputRequiredRoundsExceededError": "mcp.client._input_required",
    "ServerSession": "mcp.server.session",
    "StdioServerParameters": "mcp.client.stdio",
    "stdio_client": "mcp.client.stdio",
    "stdio_server": "mcp.server.stdio",
}
_SUBMODULES = ("client", "os", "server", "types")  # bound as the submodule itself

if TYPE_CHECKING:
    from . import types as types
    from .client._input_required import InputRequiredRoundsExceededError
    from .client.client import Client
    from .client.session import ClientSession
    from .client.session_group import ClientSessionGroup
    from .client.stdio import StdioServerParameters, stdio_client
    from .server.session import ServerSession
    from .server.stdio import stdio_server
else:

    def __getattr__(name: str) -> object:
        if name in _SUBMODULES:
            value: object = import_module(f"mcp.{name}")
        elif name in _LAZY:
            module_name = _LAZY[name]
            # Import the module's package first, as an eager `import mcp` did: importing
            # the submodule directly takes its module lock before its package's, which
            # deadlocks a thread importing a sibling that package's __init__ pulls in.
            # (Every lazy target is a direct child of mcp.client / mcp.server, and `mcp`
            # itself is complete before __getattr__ can run, so the parent suffices.)
            import_module(module_name.rpartition(".")[0])
            value = getattr(import_module(module_name), name)
        else:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        globals()[name] = value  # cache: every later access is a plain attribute lookup
        return value

    def __dir__() -> list[str]:
        return sorted(globals().keys() | _LAZY.keys() | set(_SUBMODULES))


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
    "InputRequiredRoundsExceededError",
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
    "MCPDeprecationWarning",
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
    "UriTemplate",
    "UrlElicitationRequiredError",
    "InvalidUriTemplate",
    "stdio_client",
    "stdio_server",
]
