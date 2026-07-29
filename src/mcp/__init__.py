from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

# Every name below is resolved LAZILY on first access via the module
# `__getattr__` at the bottom of this file (PEP 562), so a bare `import mcp` no
# longer imports the protocol types nor the client and server stacks. Type
# checkers still see the real bindings through these `TYPE_CHECKING` imports,
# which mirror the runtime lazy map name for name.
if TYPE_CHECKING:
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

    # Bind the `mcp.types` submodule on the package, as v1's `from .types import
    # ...` did, so `import mcp` followed by `mcp.types.Tool` keeps working. The
    # other subpackages are mirrored too: at runtime `__getattr__` imports them
    # on first attribute access (`_LAZY_SUBMODULES`), so `mcp.server.Server`
    # style chains resolve, and type checkers must see the same members.
    from . import client as client
    from . import os as os
    from . import server as server
    from . import shared as shared
    from . import types as types
    from .client._input_required import InputRequiredRoundsExceededError
    from .client.client import Client
    from .client.session import ClientSession
    from .client.session_group import ClientSessionGroup
    from .client.stdio import StdioServerParameters, stdio_client
    from .server.session import ServerSession
    from .server.stdio import stdio_server
    from .shared.exceptions import MCPDeprecationWarning, MCPError, UrlElicitationRequiredError
    from .shared.uri_template import InvalidUriTemplate, UriTemplate

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

# ---------------------------------------------------------------------------
# Lazy attributes (PEP 562).
#
# `import mcp` used to pull in the protocol types (`mcp_types`, ~500 pydantic
# models) plus the entire client and server stacks (in-memory transport ->
# lowlevel server -> transports/otel/auth) only to bind the names above.
# Every name is still here - `from mcp import Client`, `mcp.Tool`,
# `from mcp import *`, `dir(mcp)` all behave exactly as before and resolve to the
# very same objects - but each is imported from its home module on first access
# and then cached in this namespace, so `import mcp` alone is nearly free and
# each entry point pays only for what it actually uses.
# ---------------------------------------------------------------------------

_MCP_TYPES_NAMES = (
    "CallToolRequest",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CreateMessageRequest",
    "CreateMessageResult",
    "CreateMessageResultWithTools",
    "ErrorData",
    "GetPromptRequest",
    "GetPromptResult",
    "Implementation",
    "IncludeContext",
    "InitializedNotification",
    "InitializeRequest",
    "InitializeResult",
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
    "SamplingToolsCapability",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "SetLevelRequest",
    "StopReason",
    "SubscribeRequest",
    "Tool",
    "ToolChoice",
    "ToolResultContent",
    "ToolsCapability",
    "ToolUseContent",
    "UnsubscribeRequest",
)

# name -> (home module, attribute in it); mirrors the TYPE_CHECKING imports
# above name for name. (No module-level annotations here: on 3.14+ they would
# add `__annotate__`/`__conditional_annotations__` to the namespace and show up
# in `dir(mcp)`.)
_LAZY_ATTRS = {
    **{name: ("mcp_types", name) for name in _MCP_TYPES_NAMES},
    "SamplingRole": ("mcp_types", "Role"),
    "InputRequiredRoundsExceededError": ("mcp.client._input_required", "InputRequiredRoundsExceededError"),
    "Client": ("mcp.client.client", "Client"),
    "ClientSession": ("mcp.client.session", "ClientSession"),
    "ClientSessionGroup": ("mcp.client.session_group", "ClientSessionGroup"),
    "StdioServerParameters": ("mcp.client.stdio", "StdioServerParameters"),
    "stdio_client": ("mcp.client.stdio", "stdio_client"),
    "ServerSession": ("mcp.server.session", "ServerSession"),
    "stdio_server": ("mcp.server.stdio", "stdio_server"),
    "MCPDeprecationWarning": ("mcp.shared.exceptions", "MCPDeprecationWarning"),
    "MCPError": ("mcp.shared.exceptions", "MCPError"),
    "UrlElicitationRequiredError": ("mcp.shared.exceptions", "UrlElicitationRequiredError"),
    "InvalidUriTemplate": ("mcp.shared.uri_template", "InvalidUriTemplate"),
    "UriTemplate": ("mcp.shared.uri_template", "UriTemplate"),
}

# Submodules a bare `import mcp` used to bind on the package as a side effect
# of the eager imports (`mcp.types` is documented: v1's `mcp.types.Tool` idiom;
# `client`/`server`/`shared`/`os` were merely incidental). Each is imported on
# first touch; the import system then binds it here, so it is cached as well.
_LAZY_SUBMODULES = frozenset({"types", "client", "os", "server", "shared"})

# Names the lazy machinery itself adds to this namespace; kept out of
# `dir(mcp)` so it reports exactly what it did when the imports were eager.
_LAZY_MACHINERY = frozenset(
    {
        "TYPE_CHECKING",
        "_LAZY_ATTRS",
        "_LAZY_MACHINERY",
        "_LAZY_SUBMODULES",
        "_MCP_TYPES_NAMES",
        "_lazy_module_attrs",
    }
)

# Runtime-only: a type checker takes the real bindings from the TYPE_CHECKING
# imports above and must not also see a `__getattr__(name) -> object`, which
# would type every misspelled `mcp.<name>` as `object` instead of reporting it.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(
        __name__, globals(), exports=_LAZY_ATTRS, submodules=_LAZY_SUBMODULES, hidden=_LAZY_MACHINERY
    )
