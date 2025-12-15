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
# MCP Base Types
# =============================================================================


class MCPModel(BaseModel):
    """Base class for all MCP domain types. Allows extra fields for forward compatibility."""

    model_config = ConfigDict(extra="allow")


class RequestMeta(MCPModel):
    """Metadata for MCP requests."""

    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None


class RequestParams(MCPModel):
    """Base class for MCP request parameters with _meta support."""

    meta: Annotated[RequestMeta | None, Field(alias="_meta")] = None


class Meta(MCPModel):
    """Base class for MCP meta information models."""


MetaT = TypeVar("MetaT", bound=Meta | dict[str, Any] | None)


class NotificationParams(MCPModel):
    """Base class for MCP notification parameters with _meta support."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class Result(MCPModel, Generic[MetaT]):
    """Base class for MCP results with _meta support."""

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


class Icon(MCPModel):
    """An optionally-sized icon that can be displayed in a user interface."""

    src: str
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    sizes: list[str] | None = None
    theme: Literal["light", "dark"] | None = None


class Annotations(MCPModel):
    """Optional annotations for the client."""

    audience: list[Literal["user", "assistant"]] | None = None
    priority: float | None = None
    last_modified: Annotated[str | None, Field(alias="lastModified")] = None


class Implementation(MCPModel):
    """Describes the name and version of an MCP implementation."""

    name: str
    version: str
    title: str | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    website_url: Annotated[str | None, Field(alias="websiteUrl")] = None


class ClientCapabilities(MCPModel):
    """Capabilities that a client may support."""

    experimental: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None


class ServerCapabilities(MCPModel):
    """Capabilities that a server may support."""

    experimental: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    completions: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None


# =============================================================================
# Initialize
# =============================================================================


class InitializeRequestParams(RequestParams):
    """Parameters for the initialize request."""

    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]


class InitializeRequest(RequestBase[Literal["initialize"], InitializeRequestParams]):
    """Sent from client to server when first connecting."""

    method: Literal["initialize"] = "initialize"
    params: InitializeRequestParams


class InitializeResult(Result[Meta]):
    """Server's response to an initialize request."""

    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    capabilities: ServerCapabilities
    server_info: Annotated[Implementation, Field(alias="serverInfo")]
    instructions: str | None = None


class InitializedNotification(NotificationBase[Literal["notifications/initialized"], None]):
    """Sent from client to server after initialization is complete."""

    method: Literal["notifications/initialized"] = "notifications/initialized"


# =============================================================================
# Tools
# =============================================================================


class ToolExecution(MCPModel):
    """Execution-related properties for a tool."""

    task_support: Annotated[
        Literal["forbidden", "optional", "required"] | None,
        Field(alias="taskSupport"),
    ] = None


class JsonSchema(MCPModel):
    """A JSON Schema object."""

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    type: Literal["object"] = "object"
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class ToolAnnotations(MCPModel):
    """Additional properties describing a Tool to clients."""

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    title: str | None = None

class Tool(MCPModel):
    """Definition of a tool the server provides."""

    # Required fields
    input_schema: Annotated[JsonSchema, Field(alias="inputSchema")]
    name: str

    # Optional fields (spec order)
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    annotations: ToolAnnotations | None = None
    description: str | None = None
    execution: ToolExecution | None = None
    icons: list[Icon] | None = None
    output_schema: Annotated[JsonSchema | None, Field(alias="outputSchema")] = None
    title: str | None = None


class ListToolsRequestParams(RequestParams):
    """Parameters for tools/list request."""

    cursor: str | None = None


class ListToolsRequest(RequestBase[Literal["tools/list"], Optional[ListToolsRequestParams]]):
    """Request to list available tools."""

    method: Literal["tools/list"] = "tools/list"
    params: ListToolsRequestParams | None = None


class ListToolsResult(Result[Meta]):
    """Server's response to a tools/list request."""

    tools: list[Tool]
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None


class CallToolRequestParams(RequestParams):
    """Parameters for tools/call request."""

    name: str
    arguments: dict[str, Any] | None = None


class CallToolRequest(RequestBase[Literal["tools/call"], CallToolRequestParams]):
    """Request to call a tool."""

    method: Literal["tools/call"] = "tools/call"


class TextContent(MCPModel):
    """Text content in a tool result."""

    type: Literal["text"] = "text"
    text: str
    annotations: Annotations | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class CallToolResult(Result[Meta]):
    """Server's response to a tools/call request."""

    content: list[TextContent | dict[str, Any]]
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
    is_error: Annotated[bool, Field(alias="isError")] = False
