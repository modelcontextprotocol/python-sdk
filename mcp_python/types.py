from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, RootModel
from pydantic.fields import Field
from pydantic.networks import AnyUrl

"""
Model Context Protocol bindings for Python

These bindings were generated from https://github.com/anthropic-experimental/mcp-spec,
using Claude, with a prompt something like the following:

Generate idiomatic Python bindings for this schema for MCP, or the "Model Context
Protocol." The schema is defined in TypeScript, but there's also a JSON Schema version
for reference.

* For the bindings, let's use Pydantic V2 models.
* Each model should allow extra fields everywhere, by specifying `model_config =
  ConfigDict(extra='allow')`. Do this in every case, instead of a custom base class.
* Union types should be represented with a Pydantic `RootModel`.
* Define additional model classes instead of using dictionaries. Do this even if they're
  not separate types in the schema.
"""

LATEST_PROTOCOL_VERSION = "2024-10-07"

ProgressToken = str | int
Cursor = str


class RequestParams(BaseModel):
    class Meta(BaseModel):
        progressToken: ProgressToken | None = None
        """
        If specified, the caller is requesting out-of-band progress notifications for
        this request (as represented by notifications/progress). The value of this
        parameter is an opaque token that will be attached to any subsequent
        notifications. The receiver is not obligated to provide these notifications.
        """

        model_config = ConfigDict(extra="allow")

    _meta: Meta | None = None


class NotificationParams(BaseModel):
    class Meta(BaseModel):
        model_config = ConfigDict(extra="allow")

    _meta: Meta | None = None
    """
    This parameter name is reserved by MCP to allow clients and servers to attach
    additional metadata to their notifications.
    """


RequestParamsT = TypeVar("RequestParamsT", bound=RequestParams)
NotificationParamsT = TypeVar("NotificationParamsT", bound=NotificationParams)
MethodT = TypeVar("MethodT", bound=str)


class Request(BaseModel, Generic[RequestParamsT, MethodT]):
    """Base class for JSON-RPC requests."""

    method: MethodT
    params: RequestParamsT
    model_config = ConfigDict(extra="allow")


class PaginatedRequest(Request[RequestParamsT, MethodT]):
    cursor: Cursor | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class Notification(BaseModel, Generic[NotificationParamsT, MethodT]):
    """Base class for JSON-RPC notifications."""

    method: MethodT
    model_config = ConfigDict(extra="allow")


class Result(BaseModel):
    """Base class for JSON-RPC results."""

    model_config = ConfigDict(extra="allow")

    _meta: dict[str, Any] | None = None
    """
    This result property is reserved by the protocol to allow clients and servers to
    attach additional metadata to their responses.
    """


class PaginatedResult(Result):
    nextCursor: Cursor | None = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """


RequestId = str | int


class JSONRPCRequest(Request):
    """A request that expects a response."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    params: dict[str, Any] | None = None


class JSONRPCNotification(Notification):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """A successful (non-error) response to a request."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]
    model_config = ConfigDict(extra="allow")


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ErrorData(BaseModel):
    """Error information for JSON-RPC error responses."""

    code: int
    """The error type that occurred."""

    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single
    sentence.
    """

    data: Any | None = None
    """
    Additional information about the error. The value of this member is defined by the
    sender (e.g. detailed error information, nested errors etc.).
    """

    model_config = ConfigDict(extra="allow")


class JSONRPCError(BaseModel):
    """A response to a request that indicates an error occurred."""

    jsonrpc: Literal["2.0"]
    id: str | int
    error: ErrorData
    model_config = ConfigDict(extra="allow")


class JSONRPCMessage(
    RootModel[JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError]
):
    pass


class EmptyResult(Result):
    """A response that indicates success but carries no data."""


class Implementation(BaseModel):
    """Describes the name and version of an MCP implementation."""

    name: str
    version: str
    model_config = ConfigDict(extra="allow")


class ClientCapabilities(BaseModel):
    """Capabilities a client may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the client supports."""
    sampling: dict[str, Any] | None = None
    """Present if the client supports sampling from an LLM."""
    model_config = ConfigDict(extra="allow")


class ServerCapabilities(BaseModel):
    """Capabilities that a server may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the server supports."""
    logging: dict[str, Any] | None = None
    """Present if the server supports sending log messages to the client."""
    prompts: dict[str, Any] | None = None
    """Present if the server offers any prompt templates."""
    resources: dict[str, Any] | None = None
    """Present if the server offers any resources to read."""
    tools: dict[str, Any] | None = None
    """Present if the server offers any tools to call."""
    model_config = ConfigDict(extra="allow")


class InitializeRequestParams(RequestParams):
    """Parameters for the initialize request."""

    protocolVersion: str | int
    """The latest version of the Model Context Protocol that the client supports."""
    capabilities: ClientCapabilities
    clientInfo: Implementation
    model_config = ConfigDict(extra="allow")


class InitializeRequest(Request):
    """
    This request is sent from the client to the server when it first connects, asking it
    to begin initialization.
    """

    method: Literal["initialize"]
    params: InitializeRequestParams


class InitializeResult(Result):
    """After receiving an initialize request from the client, the server sends this."""

    protocolVersion: str | int
    """The version of the Model Context Protocol that the server wants to use."""
    capabilities: ServerCapabilities
    serverInfo: Implementation


class InitializedNotification(Notification):
    """
    This notification is sent from the client to the server after initialization has
    finished.
    """

    method: Literal["notifications/initialized"]
    params: NotificationParams | None = None


class PingRequest(Request):
    """
    A ping, issued by either the server or the client, to check that the other party is
    still alive.
    """

    method: Literal["ping"]
    params: RequestParams | None = None


class ProgressNotificationParams(NotificationParams):
    """Parameters for progress notifications."""

    progressToken: ProgressToken
    """
    The progress token which was given in the initial request, used to associate this
    notification with the request that is proceeding.
    """
    progress: float
    """
    The progress thus far. This should increase every time progress is made, even if the
    total is unknown.
    """
    total: float | None = None
    """Total number of items to process (or total progress required), if known."""
    model_config = ConfigDict(extra="allow")


class ProgressNotification(Notification):
    """
    An out-of-band notification used to inform the receiver of a progress update for a
    long-running request.
    """

    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class ListResourcesRequest(PaginatedRequest):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"]
    params: RequestParams | None = None


class Resource(BaseModel):
    """A known resource that the server is capable of reading."""

    uri: AnyUrl
    """The URI of this resource."""
    name: str
    """A human-readable name for this resource."""
    description: str | None = None
    """A description of what this resource represents."""
    mimeType: str | None = None
    """The MIME type of this resource, if known."""
    model_config = ConfigDict(extra="allow")


class ResourceTemplate(BaseModel):
    """A template description for resources available on the server."""

    uriTemplate: str
    """
    A URI template (according to RFC 6570) that can be used to construct resource
    URIs.
    """
    name: str
    """A human-readable name for the type of resource this template refers to."""
    description: str | None = None
    """A human-readable description of what this template is for."""
    mimeType: str | None = None
    """
    The MIME type for all resources that match this template. This should only be
    included if all resources matching this template have the same type.
    """
    model_config = ConfigDict(extra="allow")


class ListResourcesResult(PaginatedResult):
    """The server's response to a resources/list request from the client."""

    resources: list[Resource]


class ListResourceTemplatesRequest(PaginatedRequest):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"]
    params: RequestParams | None = None


class ListResourceTemplatesResult(PaginatedResult):
    """The server's response to a resources/templates/list request from the client."""

    resourceTemplates: list[ResourceTemplate]


class ReadResourceRequestParams(RequestParams):
    """Parameters for reading a resource."""

    uri: AnyUrl
    """
    The URI of the resource to read. The URI can use any protocol; it is up to the
    server how to interpret it.
    """
    model_config = ConfigDict(extra="allow")


class ReadResourceRequest(Request):
    """Sent from the client to the server, to read a specific resource URI."""

    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class ResourceContents(BaseModel):
    """The contents of a specific resource or sub-resource."""

    uri: AnyUrl
    """The URI of this resource."""
    mimeType: str | None = None
    """The MIME type of this resource, if known."""
    model_config = ConfigDict(extra="allow")


class TextResourceContents(ResourceContents):
    """Text contents of a resource."""

    text: str
    """
    The text of the item. This must only be set if the item can actually be represented
    as text (not binary data).
    """


class BlobResourceContents(ResourceContents):
    """Binary contents of a resource."""

    blob: str
    """A base64-encoded string representing the binary data of the item."""


class ReadResourceResult(Result):
    """The server's response to a resources/read request from the client."""

    contents: list[TextResourceContents | BlobResourceContents]


class ResourceListChangedNotification(Notification):
    """
    An optional notification from the server to the client, informing it that the list
    of resources it can read from has changed.
    """

    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class SubscribeRequestParams(RequestParams):
    """Parameters for subscribing to a resource."""

    uri: AnyUrl
    """
    The URI of the resource to subscribe to. The URI can use any protocol; it is up to
    the server how to interpret it.
    """
    model_config = ConfigDict(extra="allow")


class SubscribeRequest(Request):
    """
    Sent from the client to request resources/updated notifications from the server
    whenever a particular resource changes.
    """

    method: Literal["resources/subscribe"]
    params: SubscribeRequestParams


class UnsubscribeRequestParams(RequestParams):
    """Parameters for unsubscribing from a resource."""

    uri: AnyUrl
    """The URI of the resource to unsubscribe from."""
    model_config = ConfigDict(extra="allow")


class UnsubscribeRequest(Request):
    """
    Sent from the client to request cancellation of resources/updated notifications from
    the server.
    """

    method: Literal["resources/unsubscribe"]
    params: UnsubscribeRequestParams


class ResourceUpdatedNotificationParams(NotificationParams):
    """Parameters for resource update notifications."""

    uri: AnyUrl
    """
    The URI of the resource that has been updated. This might be a sub-resource of the
    one that the client actually subscribed to.
    """
    model_config = ConfigDict(extra="allow")


class ResourceUpdatedNotification(Notification):
    """
    A notification from the server to the client, informing it that a resource has
    changed and may need to be read again.
    """

    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class ListPromptsRequest(PaginatedRequest):
    """Sent from the client to request a list of prompts and prompt templates."""

    method: Literal["prompts/list"]
    params: RequestParams | None = None


class PromptArgument(BaseModel):
    """An argument for a prompt template."""

    name: str
    """The name of the argument."""
    description: str | None = None
    """A human-readable description of the argument."""
    required: bool | None = None
    """Whether this argument must be provided."""
    model_config = ConfigDict(extra="allow")


class Prompt(BaseModel):
    """A prompt or prompt template that the server offers."""

    name: str
    """The name of the prompt or prompt template."""
    description: str | None = None
    """An optional description of what this prompt provides."""
    arguments: list[PromptArgument] | None = None
    """A list of arguments to use for templating the prompt."""
    model_config = ConfigDict(extra="allow")


class ListPromptsResult(PaginatedResult):
    """The server's response to a prompts/list request from the client."""

    prompts: list[Prompt]


class GetPromptRequestParams(RequestParams):
    """Parameters for getting a prompt."""

    name: str
    """The name of the prompt or prompt template."""
    arguments: dict[str, str] | None = None
    """Arguments to use for templating the prompt."""
    model_config = ConfigDict(extra="allow")


class GetPromptRequest(Request):
    """Used by the client to get a prompt provided by the server."""

    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class TextContent(BaseModel):
    """Text content for a message."""

    type: Literal["text"]
    text: str
    """The text content of the message."""
    model_config = ConfigDict(extra="allow")


class ImageContent(BaseModel):
    """Image content for a message."""

    type: Literal["image"]
    data: str
    """The base64-encoded image data."""
    mimeType: str
    """
    The MIME type of the image. Different providers may support different
    image types.
    """
    model_config = ConfigDict(extra="allow")


Role = Literal["user", "assistant"]


class SamplingMessage(BaseModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    content: TextContent | ImageContent
    model_config = ConfigDict(extra="allow")


class GetPromptResult(Result):
    """The server's response to a prompts/get request from the client."""

    description: str | None = None
    """An optional description for the prompt."""
    messages: list[SamplingMessage]


class PromptListChangedNotification(Notification):
    """
    An optional notification from the server to the client, informing it that the list
    of prompts it offers has changed.
    """

    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class ListToolsRequest(PaginatedRequest):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"]
    params: RequestParams | None = None


class Tool(BaseModel):
    """Definition for a tool the client can call."""

    name: str
    """The name of the tool."""
    description: str | None = None
    """A human-readable description of the tool."""
    inputSchema: dict[str, Any]
    """A JSON Schema object defining the expected parameters for the tool."""
    model_config = ConfigDict(extra="allow")


class ListToolsResult(PaginatedResult):
    """The server's response to a tools/list request from the client."""

    tools: list[Tool]


class CallToolRequestParams(RequestParams):
    """Parameters for calling a tool."""

    name: str
    arguments: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


class CallToolRequest(Request):
    """Used by the client to invoke a tool provided by the server."""

    method: Literal["tools/call"]
    params: CallToolRequestParams


class CallToolResult(Result):
    """The server's response to a tool call."""

    toolResult: Any


class ToolListChangedNotification(Notification):
    """
    An optional notification from the server to the client, informing it that the list
    of tools it offers has changed.
    """

    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


LoggingLevel = Literal["debug", "info", "warning", "error"]


class SetLevelRequestParams(RequestParams):
    """Parameters for setting the logging level."""

    level: LoggingLevel
    """The level of logging that the client wants to receive from the server."""
    model_config = ConfigDict(extra="allow")


class SetLevelRequest(Request):
    """A request from the client to the server, to enable or adjust logging."""

    method: Literal["logging/setLevel"]
    params: SetLevelRequestParams


class LoggingMessageNotificationParams(NotificationParams):
    """Parameters for logging message notifications."""

    level: LoggingLevel
    """The severity of this log message."""
    logger: str | None = None
    """An optional name of the logger issuing this message."""
    data: Any
    """
    The data to be logged, such as a string message or an object. Any JSON serializable
    type is allowed here.
    """
    model_config = ConfigDict(extra="allow")


class LoggingMessageNotification(Notification):
    """Notification of a log message passed from server to client."""

    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


IncludeContext = Literal["none", "thisServer", "allServers"]


class CreateMessageRequestParams(RequestParams):
    """Parameters for creating a message."""

    messages: list[SamplingMessage]
    systemPrompt: str | None = None
    """An optional system prompt the server wants to use for sampling."""
    includeContext: IncludeContext | None = None
    """
    A request to include context from one or more MCP servers (including the caller), to
    be attached to the prompt.
    """
    temperature: float | None = None
    maxTokens: int
    """The maximum number of tokens to sample, as requested by the server."""
    stopSequences: list[str] | None = None
    metadata: dict[str, Any] | None = None
    """Optional metadata to pass through to the LLM provider."""
    model_config = ConfigDict(extra="allow")


class CreateMessageRequest(Request):
    """A request from the server to sample an LLM via the client."""

    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


StopReason = Literal["endTurn", "stopSequence", "maxTokens"]


class CreateMessageResult(Result):
    """The client's response to a sampling/create_message request from the server."""

    role: Role
    content: TextContent | ImageContent
    model: str
    """The name of the model that generated the message."""
    stopReason: StopReason
    """The reason why sampling stopped."""


class ResourceReference(BaseModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """The URI or URI template of the resource."""
    model_config = ConfigDict(extra="allow")


class PromptReference(BaseModel):
    """Identifies a prompt."""

    type: Literal["ref/prompt"]
    name: str
    """The name of the prompt or prompt template"""
    model_config = ConfigDict(extra="allow")


class CompletionArgument(BaseModel):
    """The argument's information for completion requests."""

    name: str
    """The name of the argument"""
    value: str
    """The value of the argument to use for completion matching."""
    model_config = ConfigDict(extra="allow")


class CompleteRequestParams(RequestParams):
    """Parameters for completion requests."""

    ref: ResourceReference | PromptReference
    argument: CompletionArgument
    model_config = ConfigDict(extra="allow")


class CompleteRequest(Request):
    """A request from the client to the server, to ask for completion options."""

    method: Literal["completion/complete"]
    params: CompleteRequestParams


class Completion(BaseModel):
    """Completion information."""

    values: list[str]
    """An array of completion values. Must not exceed 100 items."""
    total: int | None = None
    """
    The total number of completion options available. This can exceed the number of
    values actually sent in the response.
    """
    hasMore: bool | None = None
    """
    Indicates whether there are additional completion options beyond those provided in
    the current response, even if the exact total is unknown.
    """
    model_config = ConfigDict(extra="allow")


class CompleteResult(Result):
    """The server's response to a completion/complete request"""

    completion: Completion


class ClientRequest(
    RootModel[
        PingRequest
        | InitializeRequest
        | CompleteRequest
        | SetLevelRequest
        | GetPromptRequest
        | ListPromptsRequest
        | ListResourcesRequest
        | ListResourceTemplatesRequest
        | ReadResourceRequest
        | SubscribeRequest
        | UnsubscribeRequest
        | CallToolRequest
        | ListToolsRequest
    ]
):
    pass


class ClientNotification(RootModel[ProgressNotification | InitializedNotification]):
    pass


class ClientResult(RootModel[EmptyResult | CreateMessageResult]):
    pass


class ServerRequest(RootModel[PingRequest | CreateMessageRequest]):
    pass


class ServerNotification(
    RootModel[
        ProgressNotification
        | LoggingMessageNotification
        | ResourceUpdatedNotification
        | ResourceListChangedNotification
        | ToolListChangedNotification
        | PromptListChangedNotification
    ]
):
    pass


class ServerResult(
    RootModel[
        EmptyResult
        | InitializeResult
        | CompleteResult
        | GetPromptResult
        | ListPromptsResult
        | ListResourcesResult
        | ListResourceTemplatesResult
        | ReadResourceResult
        | CallToolResult
        | ListToolsResult
    ]
):
    pass
