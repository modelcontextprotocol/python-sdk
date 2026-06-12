"""Wire-shape models for MCP protocol version 2025-06-18 — not user-facing API.

Defines only what this revision added or changed relative to 2025-03-26;
everything else is imported from the version module that last defined it, so
every import line names the module where a model is defined.
``REMOVED_FROM_PREVIOUS_VERSION`` lists the names 2025-03-26 defined that
this revision dropped.

Consumed by ``mcp.types.wire``: ``serialize_for`` re-validates each outbound
monolith dump through the negotiated version's models, importing the version
module lazily on first boundary use (never at ``import mcp.types``).

Initially generated from the pinned 2025-06-18 schema (spec commit
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

from pydantic import ConfigDict, Field

from mcp.types._wire_base import WireModel

# Unchanged since 2024-11-05:
from mcp.types.v2024_11_05 import (
    Argument,
    CallToolRequest,
    CancelledNotification,
    CompleteResult,
    Cursor,
    EmptyResult,
    GetPromptRequest,
    InputSchema,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    LoggingLevel,
    LoggingMessageNotification,
    ModelHint,
    ModelPreferences,
    Notification,
    PaginatedRequest,
    PaginatedResult,
    PingRequest,
    ProgressToken,
    PromptListChangedNotification,
    ReadResourceRequest,
    Request,
    RequestId,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    Result,
    Role,
    Roots,
    RootsListChangedNotification,
    SetLevelRequest,
    SubscribeRequest,
    ToolListChangedNotification,
    UnsubscribeRequest,
)

# Unchanged since 2025-03-26:
from mcp.types.v2025_03_26 import (
    ProgressNotification,
    ServerCapabilities,
    ServerNotification,
    ToolAnnotations,
)

REMOVED_FROM_PREVIOUS_VERSION: Final[frozenset[str]] = frozenset(
    {
        "JSONRPCBatchRequest",
        "JSONRPCBatchResponse",
        "ResourceReference",
    }
)

__all__ = [
    "Annotations",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "BooleanSchema",
    "CallToolRequest",
    "CallToolResult",
    "CancelledNotification",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteResult",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageResult",
    "Cursor",
    "ElicitRequest",
    "ElicitResult",
    "EmbeddedResource",
    "EmptyResult",
    "EnumSchema",
    "GetPromptRequest",
    "GetPromptResult",
    "ImageContent",
    "Implementation",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
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
    "NumberSchema",
    "PaginatedRequest",
    "PaginatedResult",
    "PingRequest",
    "PrimitiveSchemaDefinition",
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
    "ResourceLink",
    "ResourceListChangedNotification",
    "ResourceTemplate",
    "ResourceTemplateReference",
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
    "StringSchema",
    "SubscribeRequest",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "ToolListChangedNotification",
    "UnsubscribeRequest",
]

# --- New in 2025-06-18 ---


class BaseMetadata(WireModel):
    """Base interface for metadata with name (identifier) and title (display name) properties."""

    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class BooleanSchema(WireModel):
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


class Context(WireModel):
    """Additional, optional context for completions"""

    arguments: dict[str, str] | None = None
    """
    Previously-resolved variables in a URI template or prompt.
    """


class ElicitResult(WireModel):
    """The client's response to an elicitation request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    action: Literal["accept", "cancel", "decline"]
    """
    The user action in response to the elicitation.
    - "accept": User submitted the form/confirmed the action
    - "decline": User explicitly declined the action
    - "cancel": User dismissed without making an explicit choice
    """
    # Deliberate deviation from the pinned schema.json, which renders the
    # value union's number arm as "integer" — its schema.ts source types form
    # answers string | number | boolean, so fractional answers are legal wire
    # values. The float arm follows schema.ts; the generated oracle keeps the
    # rendering verbatim and the surface test pins this annotation separately.
    content: dict[str, str | int | float | bool] | None = None
    """
    The submitted form data, only present when action is "accept".
    Contains values matching the requested schema.
    """


class EnumSchema(WireModel):
    description: str | None = None
    enum: list[str]
    enum_names: Annotated[list[str] | None, Field(alias="enumNames")] = None
    title: str | None = None
    type: Literal["string"]


class Params7(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class Params10(WireModel):
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class NumberSchema(WireModel):
    description: str | None = None
    # Deliberate deviation from the pinned schema.json, which renders these
    # bounds as "integer" — schema.ts types them number (JSON Schema
    # minimum/maximum are numbers; the schema describes number fields too).
    # The float arms follow schema.ts; the generated oracle keeps the
    # rendering verbatim and the surface test pins these annotations
    # separately.
    maximum: int | float | None = None
    minimum: int | float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class ResourceTemplateReference(WireModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """
    The URI or URI template of the resource.
    """


class StringSchema(WireModel):
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class OutputSchema(WireModel):
    """An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult.
    """

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class RequestedSchema(WireModel):
    """A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """

    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class ElicitRequestParams(WireModel):
    message: str
    """
    The message to present to the user.
    """
    requested_schema: Annotated[RequestedSchema, Field(alias="requestedSchema")]
    """
    A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """


class ElicitRequest(WireModel):
    """A request from the server to elicit additional information from the user via the client."""

    method: Literal["elicitation/create"]
    params: ElicitRequestParams


# --- Changed in 2025-06-18 ---


class BlobResourceContents(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    blob: str
    """
    A base64-encoded string representing the binary data of the item.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: str
    """
    The URI of this resource.
    """


class ClientCapabilities(WireModel):
    """Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any client can define its own, additional capabilities.
    """

    elicitation: dict[str, Any] | None = None
    """
    Present if the client supports elicitation from the server.
    """
    experimental: dict[str, dict[str, Any]] | None = None
    """
    Experimental, non-standard capabilities that the client supports.
    """
    roots: Roots | None = None
    """
    Present if the client supports listing roots.
    """
    sampling: dict[str, Any] | None = None
    """
    Present if the client supports sampling from an LLM.
    """


class Implementation(WireModel):
    """Describes the name and version of an MCP implementation, with an optional title for UI representation."""

    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """
    version: str


class InitializeRequestParams(WireModel):
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The latest version of the Model Context Protocol that the client supports. The client MAY decide to support older
    versions as well.
    """


class InitializeRequest(WireModel):
    """This request is sent from the client to the server when it first connects, asking it to begin initialization."""

    method: Literal["initialize"]
    params: InitializeRequestParams


class InitializedNotification(WireModel):
    """This notification is sent from the client to the server after initialization has finished."""

    method: Literal["notifications/initialized"]
    params: Params7 | None = None


class JSONRPCNotification(WireModel):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: Params7 | None = None


class ListPromptsRequest(WireModel):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    method: Literal["prompts/list"]
    params: Params10 | None = None


class ListResourceTemplatesRequest(WireModel):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"]
    params: Params10 | None = None


class ListResourcesRequest(WireModel):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"]
    params: Params10 | None = None


class ListToolsRequest(WireModel):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"]
    params: Params10 | None = None


class PromptArgument(WireModel):
    """Describes an argument that a prompt can accept."""

    description: str | None = None
    """
    A human-readable description of the argument.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    required: bool | None = None
    """
    Whether this argument must be provided.
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class PromptReference(WireModel):
    """Identifies a prompt."""

    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """
    type: Literal["ref/prompt"]


class ResourceContents(WireModel):
    """The contents of a specific resource or sub-resource."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: str
    """
    The URI of this resource.
    """


class Root(WireModel):
    """Represents a root directory or file that the server can operate on."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    name: str | None = None
    """
    An optional name for the root. This can be used to provide a human-readable
    identifier for the root, which may be useful for display purposes or for
    referencing the root in other parts of the application.
    """
    uri: str
    """
    The URI identifying the root. This *must* start with file:// for now.
    This restriction may be relaxed in future versions of the protocol to allow
    other URI schemes.
    """


class TextResourceContents(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    text: str
    """
    The text of the item. This must only be set if the item can actually be represented as text (not binary data).
    """
    uri: str
    """
    The URI of this resource.
    """


class Annotations(WireModel):
    """Optional annotations for the client. The client can use annotations to inform how objects are used or
    displayed
    """

    audience: list[Role] | None = None
    """
    Describes who the intended customer of this object or data is.

    It can include multiple entries to indicate content useful for multiple audiences (e.g., `["user", "assistant"]`).
    """
    last_modified: Annotated[str | None, Field(alias="lastModified")] = None
    """
    The moment the resource was last modified, as an ISO 8601 formatted string.

    Should be an ISO 8601 formatted string (e.g., "2025-01-12T15:00:58Z").

    Examples: last activity timestamp in an open file, timestamp when the resource
    was attached, etc.
    """
    priority: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    """
    Describes how important this data is for operating the server.

    A value of 1 means "most important," and indicates that the data is
    effectively required, while 0 means "least important," and indicates that
    the data is entirely optional.
    """


class AudioContent(WireModel):
    """Audio provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    data: str
    """
    The base64-encoded audio data.
    """
    mime_type: Annotated[str, Field(alias="mimeType")]
    """
    The MIME type of the audio. Different providers may support different audio types.
    """
    type: Literal["audio"]


class CompleteRequestParams(WireModel):
    argument: Argument
    """
    The argument's information
    """
    context: Context | None = None
    """
    Additional, optional context for completions
    """
    ref: PromptReference | ResourceTemplateReference


class CompleteRequest(WireModel):
    """A request from the client to the server, to ask for completion options."""

    method: Literal["completion/complete"]
    params: CompleteRequestParams


class EmbeddedResource(WireModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"]


class ImageContent(WireModel):
    """An image provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    data: str
    """
    The base64-encoded image data.
    """
    mime_type: Annotated[str, Field(alias="mimeType")]
    """
    The MIME type of the image. Different providers may support different image types.
    """
    type: Literal["image"]


class InitializeResult(WireModel):
    """After receiving an initialize request from the client, the server sends this response."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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


class ListRootsResult(WireModel):
    """The client's response to a roots/list request from the server.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    roots: list[Root]


class Prompt(WireModel):
    """A prompt or prompt template that the server offers."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    arguments: list[PromptArgument] | None = None
    """
    A list of arguments to use for templating the prompt.
    """
    description: str | None = None
    """
    An optional description of what this prompt provides
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class ReadResourceResult(WireModel):
    """The server's response to a resources/read request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    contents: list[TextResourceContents | BlobResourceContents]


class Resource(WireModel):
    """A known resource that the server is capable of reading."""

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
    uri: str
    """
    The URI of this resource.
    """


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


class ResourceTemplate(WireModel):
    """A template description for resources available on the server."""

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
    A description of what this template is for.

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a
    "hint" to the model.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type for all resources that match this template. This should only be included if all resources matching
    this template have the same type.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """
    uri_template: Annotated[str, Field(alias="uriTemplate")]
    """
    A URI template (according to RFC 6570) that can be used to construct resource URIs.
    """


class TextContent(WireModel):
    """Text provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    text: str
    """
    The text content of the message.
    """
    type: Literal["text"]


class Tool(WireModel):
    """Definition for a tool the client can call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: ToolAnnotations | None = None
    """
    Optional additional tool information.

    Display name precedence order is: title, annotations.title, then name.
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    output_schema: Annotated[OutputSchema | None, Field(alias="outputSchema")] = None
    """
    An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult.
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class CreateMessageResult(WireModel):
    """The client's response to a sampling/create_message request from the server. The client should inform the user
    before returning the sampled message, to allow them to inspect the response (human in the loop) and decide
    whether to allow the server to see it.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    content: TextContent | ImageContent | AudioContent
    model: str
    """
    The name of the model that generated the message.
    """
    role: Role
    stop_reason: Annotated[str | None, Field(alias="stopReason")] = None
    """
    The reason why sampling stopped, if known.
    """


class ListPromptsResult(WireModel):
    """The server's response to a prompts/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    prompts: list[Prompt]


class ListResourceTemplatesResult(WireModel):
    """The server's response to a resources/templates/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]


class ListResourcesResult(WireModel):
    """The server's response to a resources/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resources: list[Resource]


class ListToolsResult(WireModel):
    """The server's response to a tools/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    tools: list[Tool]


class PromptMessage(WireModel):
    """Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    content: ContentBlock
    role: Role


class SamplingMessage(WireModel):
    """Describes a message issued to or received from an LLM API."""

    content: TextContent | ImageContent | AudioContent
    role: Role


class CallToolResult(WireModel):
    """The server's response to a tool call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    content: list[ContentBlock]
    """
    A list of content objects that represent the unstructured result of the tool call.
    """
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """
    Whether the tool call ended in an error.

    If not set, this is assumed to be false (the call was successful).

    Any errors that originate from the tool SHOULD be reported inside the result
    object, with `isError` set to true, _not_ as an MCP protocol-level error
    response. Otherwise, the LLM would not be able to see that an error occurred
    and self-correct.

    However, any errors in _finding_ the tool, an error indicating that the
    server does not support tool calls, or any other exceptional conditions,
    should be reported as an MCP error response.
    """
    structured_content: Annotated[Any | None, Field(alias="structuredContent")] = None
    """
    An optional JSON object that represents the structured result of the tool call.
    """


class CreateMessageRequestParams(WireModel):
    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """
    A request to include context from one or more MCP servers (including the caller), to be attached to the prompt. The
    client MAY ignore this request.
    """
    max_tokens: Annotated[int, Field(alias="maxTokens")]
    """
    The requested maximum number of tokens to sample (to prevent runaway completions).

    The client MAY choose to sample fewer tokens than the requested maximum.
    """
    messages: list[SamplingMessage]
    metadata: dict[str, Any] | None = None
    """
    Optional metadata to pass through to the LLM provider. The format of this metadata is provider-specific.
    """
    model_preferences: Annotated[ModelPreferences | None, Field(alias="modelPreferences")] = None
    """
    The server's preferences for which model to select. The client MAY ignore these preferences.
    """
    stop_sequences: Annotated[list[str] | None, Field(alias="stopSequences")] = None
    system_prompt: Annotated[str | None, Field(alias="systemPrompt")] = None
    """
    An optional system prompt the server wants to use for sampling. The client MAY modify or omit this prompt.
    """
    temperature: float | None = None


class CreateMessageRequest(WireModel):
    """A request from the server to sample an LLM via the client. The client has full discretion over which model to
    select. The client should also inform the user before beginning sampling, to allow them to inspect the request
    (human in the loop) and decide whether to approve it.
    """

    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


class GetPromptResult(WireModel):
    """The server's response to a prompts/get request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    description: str | None = None
    """
    An optional description for the prompt.
    """
    messages: list[PromptMessage]


# --- Aliases new or changed in 2025-06-18 ---
# (defined last: an alias right-hand side evaluates its referents at import)

PrimitiveSchemaDefinition: TypeAlias = StringSchema | NumberSchema | BooleanSchema | EnumSchema

ClientNotification: TypeAlias = (
    CancelledNotification | InitializedNotification | ProgressNotification | RootsListChangedNotification
)

ClientRequest: TypeAlias = (
    InitializeRequest
    | PingRequest
    | ListResourcesRequest
    | ListResourceTemplatesRequest
    | ReadResourceRequest
    | SubscribeRequest
    | UnsubscribeRequest
    | ListPromptsRequest
    | GetPromptRequest
    | ListToolsRequest
    | CallToolRequest
    | SetLevelRequest
    | CompleteRequest
)

ContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource

JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError

ClientResult: TypeAlias = Result | CreateMessageResult | ListRootsResult | ElicitResult

ServerRequest: TypeAlias = PingRequest | CreateMessageRequest | ListRootsRequest | ElicitRequest

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

RequestedSchema.model_rebuild()
PromptMessage.model_rebuild()
CallToolResult.model_rebuild()
