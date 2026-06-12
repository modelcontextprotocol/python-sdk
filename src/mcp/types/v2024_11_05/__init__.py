"""Wire-shape models for MCP protocol version 2024-11-05 — not user-facing API.

The oldest supported revision, so this module defines the complete model set;
each later version module defines only what its revision added or changed and
imports everything else from the version module that last defined it.

Consumed by ``mcp.types.wire``: ``serialize_for`` re-validates each outbound
monolith dump through the negotiated version's models, importing the version
module lazily on first boundary use (never at ``import mcp.types``).

Initially generated from the pinned 2024-11-05 schema (spec commit
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

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field

from mcp.types._wire_base import OpenWireModel, WireModel

__all__ = [
    "AnnotatedModel",
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
    "ToolListChangedNotification",
    "UnsubscribeRequest",
]


class BlobResourceContents(WireModel):
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


class CallToolRequestParams(WireModel):
    arguments: dict[str, Any] | None = None
    name: str


class CallToolRequest(WireModel):
    """Used by the client to invoke a tool provided by the server."""

    method: Literal["tools/call"]
    params: CallToolRequestParams


class Roots(WireModel):
    """Present if the client supports listing roots."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether the client supports notifications for changes to the roots list.
    """


class ClientCapabilities(WireModel):
    """Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any client can define its own, additional capabilities.
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


class Argument(WireModel):
    """The argument's information"""

    name: str
    """
    The name of the argument
    """
    value: str
    """
    The value of the argument to use for completion matching.
    """


class Completion(WireModel):
    has_more: Annotated[bool | None, Field(alias="hasMore")] = None
    """
    Indicates whether there are additional completion options beyond those provided in the current response, even if the
    exact total is unknown.
    """
    total: int | None = None
    """
    The total number of completion options available. This can exceed the number of values actually sent in the
    response.
    """
    values: list[str]
    """
    An array of completion values. Must not exceed 100 items.
    """


class CompleteResult(WireModel):
    """The server's response to a completion/complete request"""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    completion: Completion


Cursor: TypeAlias = str


class GetPromptRequestParams(WireModel):
    arguments: dict[str, str] | None = None
    """
    Arguments to use for templating the prompt.
    """
    name: str
    """
    The name of the prompt or prompt template.
    """


class GetPromptRequest(WireModel):
    """Used by the client to get a prompt provided by the server."""

    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class Implementation(WireModel):
    """Describes the name and version of an MCP implementation."""

    name: str
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


class Params6(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class InitializedNotification(WireModel):
    """This notification is sent from the client to the server after initialization has finished."""

    method: Literal["notifications/initialized"]
    params: Params6 | None = None


class Error(WireModel):
    code: int
    """
    The error type that occurred.
    """
    data: Any | None = None
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """
    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single sentence.
    """


class JSONRPCNotification(WireModel):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: Params6 | None = None


class Params9(WireModel):
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class ListPromptsRequest(WireModel):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    method: Literal["prompts/list"]
    params: Params9 | None = None


class ListResourceTemplatesRequest(WireModel):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"]
    params: Params9 | None = None


class ListResourcesRequest(WireModel):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"]
    params: Params9 | None = None


class ListToolsRequest(WireModel):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"]
    params: Params9 | None = None


LoggingLevel: TypeAlias = Literal["alert", "critical", "debug", "emergency", "error", "info", "notice", "warning"]


class LoggingMessageNotificationParams(WireModel):
    data: Any
    """
    The data to be logged, such as a string message or an object. Any JSON serializable type is allowed here.
    """
    level: LoggingLevel
    """
    The severity of this log message.
    """
    logger: str | None = None
    """
    An optional name of the logger issuing this message.
    """


class LoggingMessageNotification(WireModel):
    """Notification of a log message passed from server to client. If no logging/setLevel request has been sent from
    the client, the server MAY decide which messages to send automatically.
    """

    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


class ModelHint(WireModel):
    """Hints to use for model selection.

    Keys not declared here are currently left unspecified by the spec and are up
    to the client to interpret.
    """

    name: str | None = None
    """
    A hint for a model name.

    The client SHOULD treat this as a substring of a model name; for example:
     - `claude-3-5-sonnet` should match `claude-3-5-sonnet-20241022`
     - `sonnet` should match `claude-3-5-sonnet-20241022`, `claude-3-sonnet-20240229`, etc.
     - `claude` should match any Claude model

    The client MAY also map the string to a different provider's model name or a different model family, as long as it
    fills a similar niche; for example:
     - `gemini-1.5-flash` could match `claude-3-haiku-20240307`
    """


class ModelPreferences(WireModel):
    """The server's preferences for model selection, requested of the client during sampling.

    Because LLMs can vary along multiple dimensions, choosing the "best" model is
    rarely straightforward.  Different models excel in different areas—some are
    faster but less capable, others are more capable but more expensive, and so
    on. This interface allows servers to express their priorities across multiple
    dimensions to help clients make an appropriate selection for their use case.

    These preferences are always advisory. The client MAY ignore them. It is also
    up to the client to decide how to interpret these preferences and how to
    balance them against other considerations.
    """

    cost_priority: Annotated[float | None, Field(alias="costPriority", ge=0.0, le=1.0)] = None
    """
    How much to prioritize cost when selecting a model. A value of 0 means cost
    is not important, while a value of 1 means cost is the most important
    factor.
    """
    hints: list[ModelHint] | None = None
    """
    Optional hints to use for model selection.

    If multiple hints are specified, the client MUST evaluate them in order
    (such that the first match is taken).

    The client SHOULD prioritize these hints over the numeric priorities, but
    MAY still use the priorities to select from ambiguous matches.
    """
    intelligence_priority: Annotated[float | None, Field(alias="intelligencePriority", ge=0.0, le=1.0)] = None
    """
    How much to prioritize intelligence and capabilities when selecting a
    model. A value of 0 means intelligence is not important, while a value of 1
    means intelligence is the most important factor.
    """
    speed_priority: Annotated[float | None, Field(alias="speedPriority", ge=0.0, le=1.0)] = None
    """
    How much to prioritize sampling speed (latency) when selecting a model. A
    value of 0 means speed is not important, while a value of 1 means speed is
    the most important factor.
    """


class NotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class Notification(WireModel):
    method: str
    params: NotificationParams | None = None


class PaginatedRequestParams(WireModel):
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class PaginatedRequest(WireModel):
    method: str
    params: PaginatedRequestParams | None = None


class PaginatedResult(WireModel):
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


ProgressToken: TypeAlias = str | int


class PromptArgument(WireModel):
    """Describes an argument that a prompt can accept."""

    description: str | None = None
    """
    A human-readable description of the argument.
    """
    name: str
    """
    The name of the argument.
    """
    required: bool | None = None
    """
    Whether this argument must be provided.
    """


class PromptListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class PromptListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of prompts it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    method: Literal["notifications/prompts/list_changed"]
    params: PromptListChangedNotificationParams | None = None


class PromptReference(WireModel):
    """Identifies a prompt."""

    name: str
    """
    The name of the prompt or prompt template
    """
    type: Literal["ref/prompt"]


class ReadResourceRequestParams(WireModel):
    uri: str
    """
    The URI of the resource to read. The URI can use any protocol; it is up to the server how to interpret it.
    """


class ReadResourceRequest(WireModel):
    """Sent from the client to the server, to read a specific resource URI."""

    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class Meta(OpenWireModel):
    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """
    If specified, the caller is requesting out-of-band progress notifications for this request (as represented by
    notifications/progress). The value of this parameter is an opaque token that will be attached to any subsequent
    notifications. The receiver is not obligated to provide these notifications.
    """


class RequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class Request(WireModel):
    method: str
    params: RequestParams | None = None


RequestId: TypeAlias = str | int


class ResourceContents(WireModel):
    """The contents of a specific resource or sub-resource."""

    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: str
    """
    The URI of this resource.
    """


class ResourceListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class ResourceListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of resources it can read
    from has changed. This may be issued by servers without any previous subscription from the client.
    """

    method: Literal["notifications/resources/list_changed"]
    params: ResourceListChangedNotificationParams | None = None


class ResourceReference(WireModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """
    The URI or URI template of the resource.
    """


class ResourceUpdatedNotificationParams(WireModel):
    uri: str
    """
    The URI of the resource that has been updated. This might be a sub-resource of the one that the client actually
    subscribed to.
    """


class ResourceUpdatedNotification(WireModel):
    """A notification from the server to the client, informing it that a resource has changed and may need to be read
    again. This should only be sent if the client previously sent a resources/subscribe request.
    """

    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class Result(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """


Role: TypeAlias = Literal["assistant", "user"]


class Root(WireModel):
    """Represents a root directory or file that the server can operate on."""

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


class RootsListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class RootsListChangedNotification(WireModel):
    """A notification from the client to the server, informing it that the list of roots has changed.
    This notification should be sent whenever the client adds, removes, or modifies any root.
    The server should then request an updated list of roots using the ListRootsRequest.
    """

    method: Literal["notifications/roots/list_changed"]
    params: RootsListChangedNotificationParams | None = None


class Prompts(WireModel):
    """Present if the server offers any prompt templates."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the prompt list.
    """


class Resources(WireModel):
    """Present if the server offers any resources to read."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the resource list.
    """
    subscribe: bool | None = None
    """
    Whether this server supports subscribing to resource updates.
    """


class Tools(WireModel):
    """Present if the server offers any tools to call."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the tool list.
    """


class ServerCapabilities(WireModel):
    """Capabilities that a server may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any server can define its own, additional capabilities.
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


class SetLevelRequestParams(WireModel):
    level: LoggingLevel
    """
    The level of logging that the client wants to receive from the server. The server should send all logs at this level
    and higher (i.e., more severe) to the client as notifications/message.
    """


class SetLevelRequest(WireModel):
    """A request from the client to the server, to enable or adjust logging."""

    method: Literal["logging/setLevel"]
    params: SetLevelRequestParams


class SubscribeRequestParams(WireModel):
    uri: str
    """
    The URI of the resource to subscribe to. The URI can use any protocol; it is up to the server how to interpret it.
    """


class SubscribeRequest(WireModel):
    """Sent from the client to request resources/updated notifications from the server whenever a particular resource
    changes.
    """

    method: Literal["resources/subscribe"]
    params: SubscribeRequestParams


class Annotations(WireModel):
    audience: list[Role] | None = None
    """
    Describes who the intended customer of this object or data is.

    It can include multiple entries to indicate content useful for multiple audiences (e.g., `["user", "assistant"]`).
    """
    priority: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    """
    Describes how important this data is for operating the server.

    A value of 1 means "most important," and indicates that the data is
    effectively required, while 0 means "least important," and indicates that
    the data is entirely optional.
    """


class TextContent(WireModel):
    """Text provided to or from an LLM."""

    annotations: Annotations | None = None
    text: str
    """
    The text content of the message.
    """
    type: Literal["text"]


class TextResourceContents(WireModel):
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


class InputSchema(WireModel):
    """A JSON Schema object defining the expected parameters for the tool."""

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class Tool(WireModel):
    """Definition for a tool the client can call."""

    description: str | None = None
    """
    A human-readable description of the tool.
    """
    input_schema: Annotated[InputSchema, Field(alias="inputSchema")]
    """
    A JSON Schema object defining the expected parameters for the tool.
    """
    name: str
    """
    The name of the tool.
    """


class ToolListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach additional metadata to their
    notifications.
    """


class ToolListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of tools it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    method: Literal["notifications/tools/list_changed"]
    params: ToolListChangedNotificationParams | None = None


class UnsubscribeRequestParams(WireModel):
    uri: str
    """
    The URI of the resource to unsubscribe from.
    """


class UnsubscribeRequest(WireModel):
    """Sent from the client to request cancellation of resources/updated notifications from the server. This should
    follow a previous resources/subscribe request.
    """

    method: Literal["resources/unsubscribe"]
    params: UnsubscribeRequestParams


class AnnotatedModel(WireModel):
    """Base for objects that include optional annotations for the client. The client can use annotations to inform
    how objects are used or displayed
    """

    annotations: Annotations | None = None


class CancelledNotificationParams(WireModel):
    reason: str | None = None
    """
    An optional string describing the reason for the cancellation. This MAY be logged or presented to the user.
    """
    request_id: Annotated[RequestId, Field(alias="requestId")]
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    """


class CancelledNotification(WireModel):
    """This notification can be sent by either side to indicate that it is cancelling a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it is always possible that this
    notification MAY arrive after the request has already finished.

    This notification indicates that the result will be unused, so any associated processing SHOULD cease.

    A client MUST NOT attempt to cancel its `initialize` request.
    """

    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


class CompleteRequestParams(WireModel):
    argument: Argument
    """
    The argument's information
    """
    ref: PromptReference | ResourceReference


class CompleteRequest(WireModel):
    """A request from the client to the server, to ask for completion options."""

    method: Literal["completion/complete"]
    params: CompleteRequestParams


class EmbeddedResource(WireModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    annotations: Annotations | None = None
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"]


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


EmptyResult: TypeAlias = Result


class ImageContent(WireModel):
    """An image provided to or from an LLM."""

    annotations: Annotations | None = None
    data: str
    """
    The base64-encoded image data.
    """
    mime_type: Annotated[str, Field(alias="mimeType")]
    """
    The MIME type of the image. Different providers may support different image types.
    """
    type: Literal["image"]


# Not in this version's schema (2025-03-26 introduced it): the SDK emits
# this content block to older peers unchanged rather than refusing. The only
# content arms deliberately absent from older packages are the tool blocks
# added in 2025-11-25.
class AudioContent(WireModel):
    """Audio provided to or from an LLM."""

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


class JSONRPCError(WireModel):
    """A response to a request that indicates an error occurred."""

    error: Error
    id: RequestId
    jsonrpc: Literal["2.0"]


class JSONRPCRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class JSONRPCRequest(WireModel):
    """A request that expects a response."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: JSONRPCRequestParams | None = None


class JSONRPCResponse(WireModel):
    """A successful (non-error) response to a request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class ListRootsRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class ListRootsRequest(WireModel):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    method: Literal["roots/list"]
    params: ListRootsRequestParams | None = None


class ListRootsResult(WireModel):
    """The client's response to a roots/list request from the server.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    roots: list[Root]


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


class PingRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class PingRequest(WireModel):
    """A ping, issued by either the server or the client, to check that the other party is still alive. The receiver
    must promptly respond, or else may be disconnected.
    """

    method: Literal["ping"]
    params: PingRequestParams | None = None


class ProgressNotificationParams(WireModel):
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


class Prompt(WireModel):
    """A prompt or prompt template that the server offers."""

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
    The name of the prompt or prompt template.
    """


class PromptMessage(WireModel):
    """Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    # Carries arms beyond this version's schema; see the class comments above.
    content: TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
    role: Role


class ReadResourceResult(WireModel):
    """The server's response to a resources/read request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    contents: list[TextResourceContents | BlobResourceContents]


class Resource(WireModel):
    """A known resource that the server is capable of reading."""

    annotations: Annotations | None = None
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
    A human-readable name for this resource.

    This can be used by clients to populate UI elements.
    """
    size: int | None = None
    """
    The size of the raw resource content, in bytes (i.e., before base64 encoding or any tokenization), if known.

    This can be used by Hosts to display file sizes and estimate context window usage.
    """
    uri: str
    """
    The URI of this resource.
    """


class ResourceTemplate(WireModel):
    """A template description for resources available on the server."""

    annotations: Annotations | None = None
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
    A human-readable name for the type of resource this template refers to.

    This can be used by clients to populate UI elements.
    """
    uri_template: Annotated[str, Field(alias="uriTemplate")]
    """
    A URI template (according to RFC 6570) that can be used to construct resource URIs.
    """


class SamplingMessage(WireModel):
    """Describes a message issued to or received from an LLM API."""

    # Carries arms beyond this version's schema; see the class comments above.
    content: TextContent | ImageContent | AudioContent
    role: Role


ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | LoggingMessageNotification
)


class CallToolResult(WireModel):
    """The server's response to a tool call.

    Any errors that originate from the tool SHOULD be reported inside the result
    object, with `isError` set to true, _not_ as an MCP protocol-level error
    response. Otherwise, the LLM would not be able to see that an error occurred
    and self-correct.

    However, any errors in _finding_ the tool, an error indicating that the
    server does not support tool calls, or any other exceptional conditions,
    should be reported as an MCP error response.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    # Carries arms beyond this version's schema; see the class comments above.
    content: list[TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource]
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """
    Whether the tool call ended in an error.

    If not set, this is assumed to be false (the call was successful).
    """


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
    The maximum number of tokens to sample, as requested by the server. The client MAY choose to sample fewer tokens
    than requested.
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


class CreateMessageResult(WireModel):
    """The client's response to a sampling/create_message request from the server. The client should inform the user
    before returning the sampled message, to allow them to inspect the response (human in the loop) and decide
    whether to allow the server to see it.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    # Carries arms beyond this version's schema; see the class comments above.
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


class GetPromptResult(WireModel):
    """The server's response to a prompts/get request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their
    responses.
    """
    description: str | None = None
    """
    An optional description for the prompt.
    """
    messages: list[PromptMessage]


JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError


class ListPromptsResult(WireModel):
    """The server's response to a prompts/list request from the client."""

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
    prompts: list[Prompt]


class ListResourceTemplatesResult(WireModel):
    """The server's response to a resources/templates/list request from the client."""

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
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]


class ListResourcesResult(WireModel):
    """The server's response to a resources/list request from the client."""

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
    resources: list[Resource]


ServerRequest: TypeAlias = PingRequest | CreateMessageRequest | ListRootsRequest

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

ClientResult: TypeAlias = Result | CreateMessageResult | ListRootsResult
