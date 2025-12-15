"""
V2 Types - Minimal types for MCP client operations.

Supports:
1. Connect and initialize with capabilities
2. List tools
3. Call tool and get response

Type naming follows the MCP spec (2025-11-25).
"""

from typing import Annotated, Any, Final, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from mcp_v2.types.json_rpc import NotificationBase, RequestBase

LATEST_PROTOCOL_VERSION: Final[str] = "2025-11-25"

# MCP-specific type for progress tracking
ProgressToken = str | int


# =============================================================================
# MCP Base Types (with _meta support)
# =============================================================================


class RequestMeta(BaseModel):
    """Metadata for MCP requests."""

    progressToken: ProgressToken | None = None


class RequestParams(BaseModel):
    """Base class for MCP request parameters with _meta support."""

    model_config = ConfigDict(extra="allow")

    meta: Annotated[RequestMeta | None, Field(alias="_meta")] = None


class NotificationParams(BaseModel):
    """Base class for MCP notification parameters with _meta support."""

    model_config = ConfigDict(extra="allow")

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


MetaT = TypeVar("MetaT", bound=BaseModel | dict[str, Any] | None)


class Result(BaseModel, Generic[MetaT]):
    """Base class for MCP results with _meta support."""

    model_config = ConfigDict(extra="allow")

    meta: Annotated[MetaT | None, Field(alias="_meta")] = None

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


# =============================================================================
# Common Types
# =============================================================================


class Implementation(BaseModel):
    """Describes the name and version of an MCP implementation."""

    name: str
    version: str


class ClientCapabilities(BaseModel):
    """Capabilities that a client may support."""

    experimental: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None


class ServerCapabilities(BaseModel):
    """Capabilities that a server may support."""

    experimental: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    completions: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None


# =============================================================================
# Initialize
# =============================================================================


class InitializeRequestParams(BaseModel):
    """Parameters for the initialize request."""

    protocolVersion: str
    capabilities: ClientCapabilities
    clientInfo: Implementation


class InitializeRequest(RequestBase[Literal["initialize"], InitializeRequestParams]):
    """Sent from client to server when first connecting."""

    method: Literal["initialize"] = "initialize"


class InitializeResult(BaseModel):
    """Server's response to an initialize request."""

    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: str | None = None


class InitializedNotification(NotificationBase[Literal["notifications/initialized"], None]):
    """Sent from client to server after initialization is complete."""

    method: Literal["notifications/initialized"] = "notifications/initialized"


# =============================================================================
# Tools
# =============================================================================


class Tool(BaseModel):
    """Definition of a tool the server provides."""

    name: str
    description: str | None = None
    inputSchema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class ListToolsRequestParams(BaseModel):
    """Parameters for tools/list request."""

    cursor: str | None = None


class ListToolsRequest(RequestBase[Literal["tools/list"], Optional[ListToolsRequestParams]]):
    """Request to list available tools."""

    method: Literal["tools/list"] = "tools/list"


class ListToolsResult(BaseModel):
    """Server's response to a tools/list request."""

    tools: list[Tool]
    nextCursor: str | None = None


class CallToolRequestParams(BaseModel):
    """Parameters for tools/call request."""

    name: str
    arguments: dict[str, Any] | None = None


class CallToolRequest(RequestBase[Literal["tools/call"], CallToolRequestParams]):
    """Request to call a tool."""

    method: Literal["tools/call"] = "tools/call"


class TextContent(BaseModel):
    """Text content in a tool result."""

    type: Literal["text"] = "text"
    text: str


class CallToolResult(BaseModel):
    """Server's response to a tools/call request."""

    content: list[TextContent | dict[str, Any]]
    structuredContent: dict[str, Any] | None = None
    isError: bool = False
