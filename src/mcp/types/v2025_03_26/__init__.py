"""Wire-shape models for MCP protocol version 2025-03-26 — not user-facing API.

Defines only what this revision added or changed relative to 2024-11-05;
everything else is imported from the version module that last defined it, so
every import line names the module where a model is defined.
``REMOVED_FROM_PREVIOUS_VERSION`` lists the names 2024-11-05 defined that
this revision dropped.

Consumed by ``mcp.types.wire``: ``serialize_for`` re-validates each outbound
monolith dump through the negotiated version's models, importing the version
module lazily on first boundary use (never at ``import mcp.types``).

Initially generated from the pinned 2025-03-26 schema (spec commit
6d441518de) with datamodel-code-generator 0.57.0 plus a
mechanical delta split, then hand-validated against the pinned schema.
Maintained as ordinary source: the effective surface is asserted equal to the
pinned schema by ``tests/types/test_version_surfaces.py``, so a drifting edit
fails CI.

The models are deliberately closed (``extra="ignore"``) even where the schema
declares an object open to extra fields — see ``mcp.types._wire_base`` for
the rationale. The classes kept open are commented in place.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, TypeAlias

from pydantic import Field

from mcp.types._wire_base import WireModel

# Unchanged since 2024-11-05:
from mcp.types.v2024_11_05 import (
    Annotations,
    AudioContent,
    BlobResourceContents,
    CallToolRequest,
    CallToolResult,
    CancelledNotification,
    ClientCapabilities,
    ClientRequest,
    ClientResult,
    CompleteRequest,
    CompleteResult,
    CreateMessageRequest,
    CreateMessageResult,
    Cursor,
    EmbeddedResource,
    EmptyResult,
    GetPromptRequest,
    GetPromptResult,
    ImageContent,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InputSchema,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ListRootsRequest,
    ListRootsResult,
    ListToolsRequest,
    LoggingLevel,
    LoggingMessageNotification,
    ModelHint,
    ModelPreferences,
    Notification,
    PaginatedRequest,
    PaginatedResult,
    PingRequest,
    ProgressToken,
    Prompt,
    PromptArgument,
    PromptListChangedNotification,
    PromptMessage,
    PromptReference,
    Prompts,
    ReadResourceRequest,
    ReadResourceResult,
    Request,
    RequestId,
    Resource,
    ResourceContents,
    ResourceListChangedNotification,
    ResourceReference,
    Resources,
    ResourceTemplate,
    ResourceUpdatedNotification,
    Result,
    Role,
    Root,
    RootsListChangedNotification,
    SamplingMessage,
    ServerRequest,
    SetLevelRequest,
    SubscribeRequest,
    TextContent,
    TextResourceContents,
    ToolListChangedNotification,
    Tools,
    UnsubscribeRequest,
)

REMOVED_FROM_PREVIOUS_VERSION: Final[frozenset[str]] = frozenset(
    {
        "AnnotatedModel",
    }
)

__all__ = [
    "Annotations",
    "AudioContent",
    "BlobResourceContents",
    "CallToolRequest",
    "CallToolResult",
    "CancelledNotification",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteResult",
    "CreateMessageRequest",
    "CreateMessageResult",
    "Cursor",
    "EmbeddedResource",
    "EmptyResult",
    "GetPromptRequest",
    "GetPromptResult",
    "ImageContent",
    "Implementation",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCBatchRequest",
    "JSONRPCBatchResponse",
    "JSONRPCError",
    "JSONRPCMessage",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourceTemplatesRequest",
    "ListResourceTemplatesResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListRootsRequest",
    "ListRootsResult",
    "ListToolsRequest",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "ModelHint",
    "ModelPreferences",
    "Notification",
    "PaginatedRequest",
    "PaginatedResult",
    "PingRequest",
    "ProgressNotification",
    "ProgressToken",
    "Prompt",
    "PromptArgument",
    "PromptListChangedNotification",
    "PromptMessage",
    "PromptReference",
    "ReadResourceRequest",
    "ReadResourceResult",
    "Request",
    "RequestId",
    "Resource",
    "ResourceContents",
    "ResourceListChangedNotification",
    "ResourceReference",
    "ResourceTemplate",
    "ResourceUpdatedNotification",
    "Result",
    "Role",
    "Root",
    "RootsListChangedNotification",
    "SamplingMessage",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "SetLevelRequest",
    "SubscribeRequest",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "ToolListChangedNotification",
    "UnsubscribeRequest",
]

# --- New in 2025-03-26 ---


class ToolAnnotations(WireModel):
    """Additional properties describing a Tool to clients.

    NOTE: all properties in ToolAnnotations are **hints**.
    They are not guaranteed to provide a faithful description of
    tool behavior (including descriptive properties like `title`).

    Clients should never make tool use decisions based on ToolAnnotations
    received from untrusted servers.
    """

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    """
    If true, the tool may perform destructive updates to its environment.
    If false, the tool performs only additive updates.

    (This property is meaningful only when `readOnlyHint == false`)

    Default: true
    """
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    """
    If true, calling the tool repeatedly with the same arguments
    will have no additional effect on the its environment.

    (This property is meaningful only when `readOnlyHint == false`)

    Default: false
    """
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    """
    If true, this tool may interact with an "open world" of external
    entities. If false, the tool's domain of interaction is closed.
    For example, the world of a web search tool is open, whereas that
    of a memory tool is not.

    Default: true
    """
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    """
    If true, the tool does not modify its environment.

    Default: false
    """
    title: str | None = None
    """
    A human-readable title for the tool.
    """


# --- Changed in 2025-03-26 ---


class ServerCapabilities(WireModel):
    """Capabilities that a server may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any server can define its own, additional capabilities.
    """

    completions: dict[str, Any] | None = None
    """
    Present if the server supports argument autocompletion suggestions.
    """
    experimental: dict[str, dict[str, Any]] | None = None
    """
    Experimental, non-standard capabilities that the server supports.
    """
    logging: dict[str, Any] | None = None
    """
    Present if the server supports sending log messages to the client.
    """
    prompts: Prompts | None = None
    """
    Present if the server offers any prompt templates.
    """
    resources: Resources | None = None
    """
    Present if the server offers any resources to read.
    """
    tools: Tools | None = None
    """
    Present if the server offers any tools to call.
    """


class InitializeResult(WireModel):
    """After receiving an initialize request from the client, the server sends this response."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    capabilities: ServerCapabilities
    instructions: str | None = None
    """
    Instructions describing how to use the server and its features.

    This can be used by clients to improve the LLM's understanding of available tools, resources, etc. It can be thought
    of like a "hint" to the model. For example, this information MAY be added to the system prompt.
    """
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The version of the Model Context Protocol that the server wants to use. This may not match the version that the
    client requested. If the client cannot support this version, it MUST disconnect.
    """
    server_info: Annotated[Implementation, Field(alias="serverInfo")]


class ProgressNotificationParams(WireModel):
    message: str | None = None
    """
    An optional message describing the current progress.
    """
    progress: float
    """
    The progress thus far. This should increase every time progress is made, even if the total is unknown.
    """
    progress_token: Annotated[ProgressToken, Field(alias="progressToken")]
    """
    The progress token which was given in the initial request, used to associate this notification with the request that
    is proceeding.
    """
    total: float | None = None
    """
    Total number of items to process (or total progress required), if known.
    """


class ProgressNotification(WireModel):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class Tool(WireModel):
    """Definition for a tool the client can call."""

    annotations: ToolAnnotations | None = None
    """
    Optional additional tool information.
    """
    description: str | None = None
    """
    A human-readable description of the tool.

    This can be used by clients to improve the LLM's understanding of available tools. It can be thought of like a
    "hint" to the model.
    """
    input_schema: Annotated[InputSchema, Field(alias="inputSchema")]
    """
    A JSON Schema object defining the expected parameters for the tool.
    """
    name: str
    """
    The name of the tool.
    """


class ListToolsResult(WireModel):
    """The server's response to a tools/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    tools: list[Tool]


# Not in this version's schema (2025-06-18 introduced it): the SDK emits
# this content block to older peers unchanged rather than refusing. The only
# content arms deliberately absent from older packages are the tool blocks
# added in 2025-11-25.
class ResourceLink(WireModel):
    """A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    description: str | None = None
    """
    A description of what this resource represents.

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a
    "hint" to the model.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    size: int | None = None
    """
    The size of the raw resource content, in bytes (i.e., before base64 encoding or any tokenization), if known.

    This can be used by Hosts to display file sizes and estimate context window usage.
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """
    type: Literal["resource_link"]
    uri: str
    """
    The URI of this resource.
    """


# --- Aliases new or changed in 2025-03-26 ---
# (defined last: an alias right-hand side evaluates its referents at import)

ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | LoggingMessageNotification
)

ClientNotification: TypeAlias = (
    CancelledNotification | InitializedNotification | ProgressNotification | RootsListChangedNotification
)

JSONRPCBatchRequest: TypeAlias = list[JSONRPCRequest | JSONRPCNotification]

JSONRPCBatchResponse: TypeAlias = list[JSONRPCResponse | JSONRPCError]

JSONRPCMessage: TypeAlias = (
    JSONRPCRequest
    | JSONRPCNotification
    | list[JSONRPCRequest | JSONRPCNotification]
    | JSONRPCResponse
    | JSONRPCError
    | list[JSONRPCResponse | JSONRPCError]
)

ServerResult: TypeAlias = (
    Result
    | InitializeResult
    | ListResourcesResult
    | ListResourceTemplatesResult
    | ReadResourceResult
    | ListPromptsResult
    | GetPromptResult
    | ListToolsResult
    | CallToolResult
    | CompleteResult
)
