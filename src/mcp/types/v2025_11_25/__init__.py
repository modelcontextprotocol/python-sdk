"""Internal wire-shape models for protocol 2025-11-25. Not part of the public API.

Serves inbound validation for every protocol version through 2025-11-25 (each
earlier schema is a strict subset of this one). Models default to
`extra="ignore"`; the few kept open are commented in place. See
`mcp.types._wire_base` and `mcp.types.methods`.
Pinned to schema/2025-11-25/schema.json @ 6d441518de8a9d5adbab0b10a76a667a63f90665.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field

from mcp.types._wire_base import OpenWireModel, WireModel


class BaseMetadata(WireModel):
    """Base interface for metadata with name (identifier) and title (display name)."""

    name: str
    """Programmatic identifier; also the display fallback when `title` is absent."""
    title: str | None = None
    """Human-readable display name."""


class BlobResourceContents(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    blob: str
    """Base64-encoded binary data."""
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    uri: str


class BooleanSchema(WireModel):
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


class CancelTaskRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]


class Elicitation(WireModel):
    """Present if the client supports elicitation from the server."""

    form: dict[str, Any] | None = None
    url: dict[str, Any] | None = None


class Roots(WireModel):
    """Present if the client supports listing roots."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None


class Sampling(WireModel):
    """Present if the client supports sampling from an LLM."""

    context: dict[str, Any] | None = None
    """Present if the client supports the `includeContext` parameter."""
    tools: dict[str, Any] | None = None
    """Present if the client supports the `tools` and `toolChoice` parameters."""


class Elicitation1(WireModel):
    """Task support for elicitation-related requests."""

    create: dict[str, Any] | None = None


class Sampling1(WireModel):
    """Task support for sampling-related requests."""

    create_message: Annotated[dict[str, Any] | None, Field(alias="createMessage")] = None


class Requests(WireModel):
    """Specifies which request types can be augmented with tasks."""

    elicitation: Elicitation1 | None = None
    sampling: Sampling1 | None = None


class Tasks(WireModel):
    """Present if the client supports task-augmented requests."""

    cancel: dict[str, Any] | None = None
    list: dict[str, Any] | None = None
    requests: Requests | None = None


class ClientCapabilities(WireModel):
    """Capabilities a client may support. Not a closed set."""

    elicitation: Elicitation | None = None
    experimental: dict[str, dict[str, Any]] | None = None
    roots: Roots | None = None
    sampling: Sampling | None = None
    tasks: Tasks | None = None


class Argument(WireModel):
    """The argument being completed."""

    name: str
    value: str


class Context(WireModel):
    """Additional context for completions."""

    arguments: dict[str, str] | None = None
    """Already-resolved variables in a URI template or prompt."""


class Completion(WireModel):
    has_more: Annotated[bool | None, Field(alias="hasMore")] = None
    total: int | None = None
    values: list[str]
    """Must not exceed 100 items."""


class CompleteResult(WireModel):
    """The server's response to a completion/complete request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    completion: Completion


Cursor: TypeAlias = str


class ElicitResult(WireModel):
    """The client's response to an elicitation request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    action: Literal["accept", "cancel", "decline"]
    # Deviation: schema.json renders the number arm as "integer" but schema.ts
    # types it `number`, so fractional answers are legal. Follow schema.ts.
    content: dict[str, list[str] | str | int | float | bool] | None = None
    """Submitted form data; only present when action is "accept" and mode was "form"."""


class ElicitationCompleteNotificationParams(WireModel):
    elicitation_id: Annotated[str, Field(alias="elicitationId")]


class ElicitationCompleteNotification(WireModel):
    """Server-to-client notification that an out-of-band elicitation completed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/elicitation/complete"]
    params: ElicitationCompleteNotificationParams


class Error(WireModel):
    code: int
    data: Any | None = None
    message: str


class GetTaskPayloadRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]


class GetTaskPayloadResult(WireModel):
    """Response to tasks/result; structure matches the original request's result type."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


class GetTaskRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]


class Icon(WireModel):
    """An optionally-sized icon that can be displayed in a user interface."""

    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    sizes: list[str] | None = None
    """Each entry is WxH (e.g. "48x48") or "any" for scalable formats."""
    src: str
    """HTTP/HTTPS URL or `data:` URI."""
    theme: Literal["dark", "light"] | None = None


class Icons(WireModel):
    """Base interface adding an `icons` property."""

    icons: list[Icon] | None = None


class Implementation(WireModel):
    """Describes the MCP implementation."""

    description: str | None = None
    icons: list[Icon] | None = None
    name: str
    title: str | None = None
    version: str
    website_url: Annotated[str | None, Field(alias="websiteUrl")] = None


class JSONRPCNotification(WireModel):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class LegacyTitledEnumSchema(WireModel):
    """Use TitledSingleSelectEnumSchema instead."""

    default: str | None = None
    description: str | None = None
    enum: list[str]
    enum_names: Annotated[list[str] | None, Field(alias="enumNames")] = None
    """Display names for enum values (legacy, non-standard JSON Schema)."""
    title: str | None = None
    type: Literal["string"]


LoggingLevel: TypeAlias = Literal["alert", "critical", "debug", "emergency", "error", "info", "notice", "warning"]


class LoggingMessageNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    data: Any
    level: LoggingLevel
    logger: str | None = None


class ModelHint(WireModel):
    """Hints to use for model selection."""

    name: str | None = None
    """Substring of a model name; the client may map it to another provider's equivalent."""


class ModelPreferences(WireModel):
    """The server's advisory preferences for model selection during sampling."""

    cost_priority: Annotated[float | None, Field(alias="costPriority", ge=0.0, le=1.0)] = None
    hints: list[ModelHint] | None = None
    """Evaluated in order; first match wins."""
    intelligence_priority: Annotated[float | None, Field(alias="intelligencePriority", ge=0.0, le=1.0)] = None
    speed_priority: Annotated[float | None, Field(alias="speedPriority", ge=0.0, le=1.0)] = None


class Notification(WireModel):
    method: str
    params: dict[str, Any] | None = None


class NotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


class NumberSchema(WireModel):
    # Deviation: schema.json renders these as "integer" but schema.ts types
    # them `number` (JSON Schema bounds are numbers). Follow schema.ts.
    default: int | float | None = None
    description: str | None = None
    maximum: int | float | None = None
    minimum: int | float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class PaginatedResult(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination token; if present, more results may be available."""


ProgressToken: TypeAlias = str | int


class PromptArgument(WireModel):
    """Describes an argument that a prompt can accept."""

    description: str | None = None
    name: str
    required: bool | None = None
    title: str | None = None


class PromptListChangedNotification(WireModel):
    """Server-to-client notification that the prompt list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class PromptReference(WireModel):
    """Identifies a prompt."""

    name: str
    title: str | None = None
    type: Literal["ref/prompt"]


class Meta(OpenWireModel):
    """Request `_meta` object."""

    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """If set, the caller wants `notifications/progress` for this request, tagged with this token."""


class ReadResourceRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    uri: str


class RelatedTaskMetadata(WireModel):
    """Associates a message with a task via `_meta["io.modelcontextprotocol/related-task"]`."""

    task_id: Annotated[str, Field(alias="taskId")]


class Request(WireModel):
    method: str
    params: dict[str, Any] | None = None


RequestId: TypeAlias = str | int


class RequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class ResourceContents(WireModel):
    """The contents of a specific resource or sub-resource."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    uri: str


class ResourceListChangedNotification(WireModel):
    """Server-to-client notification that the resource list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class ResourceRequestParams(WireModel):
    """Common parameters when working with resources."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    uri: str


class ResourceTemplateReference(WireModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """The URI or URI template of the resource."""


class ResourceUpdatedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    uri: str
    """May be a sub-resource of the one the client subscribed to."""


class Result(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


Role: TypeAlias = Literal["assistant", "user"]


class Root(WireModel):
    """A root directory or file that the server can operate on."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    name: str | None = None
    uri: str
    """Must start with file:// for now."""


class RootsListChangedNotification(WireModel):
    """Client-to-server notification that the roots list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/roots/list_changed"]
    params: NotificationParams | None = None


class Prompts(WireModel):
    """Present if the server offers any prompt templates."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None


class Resources(WireModel):
    """Present if the server offers any resources to read."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    subscribe: bool | None = None


class Tools(WireModel):
    """Task support for tool-related requests."""

    call: dict[str, Any] | None = None


class Requests1(WireModel):
    """Specifies which request types can be augmented with tasks."""

    tools: Tools | None = None


class Tasks1(WireModel):
    """Present if the server supports task-augmented requests."""

    cancel: dict[str, Any] | None = None
    list: dict[str, Any] | None = None
    requests: Requests1 | None = None


class Tools1(WireModel):
    """Present if the server offers any tools to call."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None


class ServerCapabilities(WireModel):
    """Capabilities a server may support. Not a closed set."""

    completions: dict[str, Any] | None = None
    experimental: dict[str, dict[str, Any]] | None = None
    logging: dict[str, Any] | None = None
    prompts: Prompts | None = None
    resources: Resources | None = None
    tasks: Tasks1 | None = None
    tools: Tools1 | None = None


class SetLevelRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    level: LoggingLevel
    """Minimum severity to send to the client as notifications/message."""


class StringSchema(WireModel):
    default: str | None = None
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class SubscribeRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    uri: str


class TaskMetadata(WireModel):
    """Metadata for augmenting a request with task execution (the `task` param field)."""

    ttl: int | None = None
    """Requested retention from creation, in milliseconds."""


TaskStatus: TypeAlias = Literal["cancelled", "completed", "failed", "input_required", "working"]


class TextResourceContents(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    text: str
    uri: str


class AnyOfItem(WireModel):
    const: str
    title: str


class Items(WireModel):
    """Schema for array items with enum options and display labels."""

    any_of: Annotated[list[AnyOfItem], Field(alias="anyOf")]


class TitledMultiSelectEnumSchema(WireModel):
    """Multiple-selection enum with display titles for each option."""

    default: list[str] | None = None
    description: str | None = None
    items: Items
    max_items: Annotated[int | None, Field(alias="maxItems")] = None
    min_items: Annotated[int | None, Field(alias="minItems")] = None
    title: str | None = None
    type: Literal["array"]


class OneOfItem(WireModel):
    const: str
    title: str


class TitledSingleSelectEnumSchema(WireModel):
    """Single-selection enum with display titles for each option."""

    default: str | None = None
    description: str | None = None
    one_of: Annotated[list[OneOfItem], Field(alias="oneOf")]
    title: str | None = None
    type: Literal["string"]


class InputSchema(WireModel):
    """A JSON Schema object defining the expected parameters for the tool."""

    # Kept open: arbitrary JSON Schema keywords ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class OutputSchema(WireModel):
    """A JSON Schema object defining the structure of `CallToolResult.structuredContent`."""

    # Kept open: arbitrary JSON Schema keywords ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class ToolAnnotations(WireModel):
    """Untrusted hints describing a tool's behavior to clients."""

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    """Only meaningful when `readOnlyHint` is false. Default: true."""
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    """Only meaningful when `readOnlyHint` is false. Default: false."""
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    """Default: true."""
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    """Default: false."""
    title: str | None = None


class ToolChoice(WireModel):
    """Controls tool selection behavior for sampling requests."""

    mode: Literal["auto", "none", "required"] | None = None


class ToolExecution(WireModel):
    """Execution-related properties for a tool."""

    task_support: Annotated[Literal["forbidden", "optional", "required"] | None, Field(alias="taskSupport")] = None
    """Whether this tool supports task-augmented execution. Default: "forbidden"."""


class ToolListChangedNotification(WireModel):
    """Server-to-client notification that the tool list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


class ToolUseContent(WireModel):
    """A request from the assistant to call a tool."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    id: str
    """Unique identifier matched against `ToolResultContent.tool_use_id`."""
    input: dict[str, Any]
    name: str
    type: Literal["tool_use"]


class UnsubscribeRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    uri: str


class Items1(WireModel):
    """Schema for the array items."""

    enum: list[str]
    type: Literal["string"]


class UntitledMultiSelectEnumSchema(WireModel):
    """Multiple-selection enum without per-option display titles."""

    default: list[str] | None = None
    description: str | None = None
    items: Items1
    max_items: Annotated[int | None, Field(alias="maxItems")] = None
    min_items: Annotated[int | None, Field(alias="minItems")] = None
    title: str | None = None
    type: Literal["array"]


class UntitledSingleSelectEnumSchema(WireModel):
    """Single-selection enum without per-option display titles."""

    default: str | None = None
    description: str | None = None
    enum: list[str]
    title: str | None = None
    type: Literal["string"]


class Annotations(WireModel):
    """Optional annotations for the client."""

    audience: list[Role] | None = None
    last_modified: Annotated[str | None, Field(alias="lastModified")] = None
    """ISO 8601 timestamp."""
    priority: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    """1 means effectively required, 0 means entirely optional."""


class AudioContent(WireModel):
    """Audio provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    data: str
    """Base64-encoded audio data."""
    mime_type: Annotated[str, Field(alias="mimeType")]
    type: Literal["audio"]


class CallToolRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    arguments: dict[str, Any] | None = None
    name: str
    task: TaskMetadata | None = None
    """If set, run as a task and return `CreateTaskResult` immediately."""


class CancelTaskRequest(WireModel):
    """A request to cancel a task."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/cancel"]
    params: CancelTaskRequestParams


class CancelledNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    reason: str | None = None
    request_id: Annotated[RequestId | None, Field(alias="requestId")] = None
    """Required for non-task requests; MUST NOT be used for tasks (use `tasks/cancel`)."""


class CompleteRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    argument: Argument
    context: Context | None = None
    ref: PromptReference | ResourceTemplateReference


class ElicitRequestURLParams(WireModel):
    """Parameters for a URL-mode elicitation request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """Server-unique opaque ID."""
    message: str
    mode: Literal["url"]
    task: TaskMetadata | None = None
    """If set, run as a task and return `CreateTaskResult` immediately."""
    url: str


class EmbeddedResource(WireModel):
    """The contents of a resource, embedded into a prompt or tool call result."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"]


EmptyResult: TypeAlias = Result


EnumSchema: TypeAlias = (
    UntitledSingleSelectEnumSchema
    | TitledSingleSelectEnumSchema
    | UntitledMultiSelectEnumSchema
    | TitledMultiSelectEnumSchema
    | LegacyTitledEnumSchema
)


class GetPromptRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    arguments: dict[str, str] | None = None
    name: str


class GetTaskPayloadRequest(WireModel):
    """A request to retrieve the result of a completed task."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/result"]
    params: GetTaskPayloadRequestParams


class GetTaskRequest(WireModel):
    """A request to retrieve the state of a task."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/get"]
    params: GetTaskRequestParams


class ImageContent(WireModel):
    """An image provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    data: str
    """Base64-encoded image data."""
    mime_type: Annotated[str, Field(alias="mimeType")]
    type: Literal["image"]


class InitializeRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """The latest protocol version the client supports."""


class InitializeResult(WireModel):
    """The server's response to an initialize request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    capabilities: ServerCapabilities
    instructions: str | None = None
    """Instructions describing how to use the server and its features."""
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """The protocol version the server wants to use; the client MUST disconnect if unsupported."""
    server_info: Annotated[Implementation, Field(alias="serverInfo")]


class InitializedNotification(WireModel):
    """Sent from the client to the server after initialization has finished."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/initialized"]
    params: NotificationParams | None = None


class JSONRPCErrorResponse(WireModel):
    """A response to a request that indicates an error occurred."""

    error: Error
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class JSONRPCRequest(WireModel):
    """A request that expects a response."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResultResponse(WireModel):
    """A successful (non-error) response to a request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class ListRootsRequest(WireModel):
    """Sent from the server to request a list of root URIs from the client."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["roots/list"]
    params: RequestParams | None = None


class ListRootsResult(WireModel):
    """The client's response to a roots/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    roots: list[Root]


class LoggingMessageNotification(WireModel):
    """A log message passed from server to client."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


MultiSelectEnumSchema: TypeAlias = UntitledMultiSelectEnumSchema | TitledMultiSelectEnumSchema


class PaginatedRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    cursor: str | None = None
    """Opaque pagination token; results start after this position."""


class PingRequest(WireModel):
    """A ping, issued by either side, to check that the other party is still alive."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["ping"]
    params: RequestParams | None = None


PrimitiveSchemaDefinition: TypeAlias = (
    StringSchema
    | NumberSchema
    | BooleanSchema
    | UntitledSingleSelectEnumSchema
    | TitledSingleSelectEnumSchema
    | UntitledMultiSelectEnumSchema
    | TitledMultiSelectEnumSchema
    | LegacyTitledEnumSchema
)


class ProgressNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    message: str | None = None
    progress: float
    """Monotonically increasing, even if `total` is unknown."""
    progress_token: Annotated[ProgressToken, Field(alias="progressToken")]
    """The token from the originating request's `_meta.progressToken`."""
    total: float | None = None


class Prompt(WireModel):
    """A prompt or prompt template that the server offers."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    arguments: list[PromptArgument] | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    name: str
    title: str | None = None


class ReadResourceRequest(WireModel):
    """Sent from the client to read a specific resource URI."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class ReadResourceResult(WireModel):
    """The server's response to a resources/read request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    contents: list[TextResourceContents | BlobResourceContents]


class Resource(WireModel):
    """A known resource that the server is capable of reading."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    name: str
    size: int | None = None
    """Raw content size in bytes (before base64 encoding), if known."""
    title: str | None = None
    uri: str


class ResourceLink(WireModel):
    """A resource link included in a prompt or tool call result."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    name: str
    size: int | None = None
    """Raw content size in bytes (before base64 encoding), if known."""
    title: str | None = None
    type: Literal["resource_link"]
    uri: str


class ResourceTemplate(WireModel):
    """A template description for resources available on the server."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """Only set if all resources matching this template share the same type."""
    name: str
    title: str | None = None
    uri_template: Annotated[str, Field(alias="uriTemplate")]
    """RFC 6570 URI template."""


class ResourceUpdatedNotification(WireModel):
    """Server-to-client notification that a subscribed resource has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class SetLevelRequest(WireModel):
    """A request from the client to enable or adjust logging."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["logging/setLevel"]
    params: SetLevelRequestParams


SingleSelectEnumSchema: TypeAlias = UntitledSingleSelectEnumSchema | TitledSingleSelectEnumSchema


class SubscribeRequest(WireModel):
    """Sent from the client to request resources/updated notifications for a resource."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/subscribe"]
    params: SubscribeRequestParams


class Task(WireModel):
    """Data associated with a task."""

    created_at: Annotated[str, Field(alias="createdAt")]
    """ISO 8601 timestamp."""
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """ISO 8601 timestamp."""
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """Suggested polling interval in milliseconds."""
    status: TaskStatus
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    task_id: Annotated[str, Field(alias="taskId")]
    ttl: int | None
    """Actual retention from creation in milliseconds; null means unlimited."""


class TaskAugmentedRequestParams(WireModel):
    """Common params for any task-augmented request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    task: TaskMetadata | None = None
    """If set, run as a task and return `CreateTaskResult` immediately."""


class TaskStatusNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    """ISO 8601 timestamp."""
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """ISO 8601 timestamp."""
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """Suggested polling interval in milliseconds."""
    status: TaskStatus
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    task_id: Annotated[str, Field(alias="taskId")]
    ttl: int | None
    """Actual retention from creation in milliseconds; null means unlimited."""


class TextContent(WireModel):
    """Text provided to or from an LLM."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    text: str
    type: Literal["text"]


class Tool(WireModel):
    """Definition for a tool the client can call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    annotations: ToolAnnotations | None = None
    description: str | None = None
    execution: ToolExecution | None = None
    icons: list[Icon] | None = None
    input_schema: Annotated[InputSchema, Field(alias="inputSchema")]
    name: str
    output_schema: Annotated[OutputSchema | None, Field(alias="outputSchema")] = None
    title: str | None = None


class Data(WireModel):
    """Error data carrying pending URL elicitations."""

    elicitations: list[ElicitRequestURLParams]


class Error1(WireModel):
    code: Literal[-32042]
    data: Data
    message: str


class URLElicitationRequiredError(WireModel):
    """Error response indicating the server requires a URL-mode elicitation."""

    error: Error1
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class UnsubscribeRequest(WireModel):
    """Sent from the client to cancel resources/updated notifications for a resource."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/unsubscribe"]
    params: UnsubscribeRequestParams


class CallToolRequest(WireModel):
    """Used by the client to invoke a tool provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/call"]
    params: CallToolRequestParams


class CancelTaskResult(WireModel):
    """The response to a tasks/cancel request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    """ISO 8601 timestamp."""
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """ISO 8601 timestamp."""
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """Suggested polling interval in milliseconds."""
    status: TaskStatus
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    task_id: Annotated[str, Field(alias="taskId")]
    ttl: int | None
    """Actual retention from creation in milliseconds; null means unlimited."""


class CancelledNotification(WireModel):
    """Sent by either side to cancel an in-flight request (not for tasks; use `tasks/cancel`)."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


class CompleteRequest(WireModel):
    """A request from the client to ask for completion options."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["completion/complete"]
    params: CompleteRequestParams


ContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource


class CreateTaskResult(WireModel):
    """A response to a task-augmented request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    task: Task


class RequestedSchema(WireModel):
    """A restricted JSON Schema subset: top-level properties only, no nesting."""

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class ElicitRequestFormParams(WireModel):
    """Parameters for a form-mode elicitation request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    message: str
    mode: Literal["form"] = "form"
    requested_schema: Annotated[RequestedSchema, Field(alias="requestedSchema")]
    task: TaskMetadata | None = None
    """If set, run as a task and return `CreateTaskResult` immediately."""


ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams


class GetPromptRequest(WireModel):
    """Used by the client to get a prompt provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class GetTaskResult(WireModel):
    """The response to a tasks/get request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    """ISO 8601 timestamp."""
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """ISO 8601 timestamp."""
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """Suggested polling interval in milliseconds."""
    status: TaskStatus
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    task_id: Annotated[str, Field(alias="taskId")]
    ttl: int | None
    """Actual retention from creation in milliseconds; null means unlimited."""


class InitializeRequest(WireModel):
    """Sent from the client to the server when it first connects."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["initialize"]
    params: InitializeRequestParams


JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse


JSONRPCResponse: TypeAlias = JSONRPCResultResponse | JSONRPCErrorResponse


class ListPromptsRequest(WireModel):
    """Sent from the client to request a list of prompts and prompt templates."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/list"]
    params: PaginatedRequestParams | None = None


class ListPromptsResult(WireModel):
    """The server's response to a prompts/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    prompts: list[Prompt]


class ListResourceTemplatesRequest(WireModel):
    """Sent from the client to request a list of resource templates."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/templates/list"]
    params: PaginatedRequestParams | None = None


class ListResourceTemplatesResult(WireModel):
    """The server's response to a resources/templates/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]


class ListResourcesRequest(WireModel):
    """Sent from the client to request a list of resources."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/list"]
    params: PaginatedRequestParams | None = None


class ListResourcesResult(WireModel):
    """The server's response to a resources/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    resources: list[Resource]


class ListTasksRequest(WireModel):
    """A request to retrieve a list of tasks."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/list"]
    params: PaginatedRequestParams | None = None


class ListTasksResult(WireModel):
    """The response to a tasks/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    tasks: list[Task]


class ListToolsRequest(WireModel):
    """Sent from the client to request a list of tools."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/list"]
    params: PaginatedRequestParams | None = None


class ListToolsResult(WireModel):
    """The server's response to a tools/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    tools: list[Tool]


class PaginatedRequest(WireModel):
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: PaginatedRequestParams | None = None


class ProgressNotification(WireModel):
    """An out-of-band progress update for a long-running request."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class PromptMessage(WireModel):
    """A message returned as part of a prompt; like `SamplingMessage` but allows embedded resources."""

    content: ContentBlock
    role: Role


class TaskStatusNotification(WireModel):
    """An optional notification that a task's status has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tasks/status"]
    params: TaskStatusNotificationParams


class ToolResultContent(WireModel):
    """The result of a tool use, provided by the user back to the assistant."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    content: list[ContentBlock]
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """Default: false."""
    # 2025-11-25 schema: object-only; 2026-07-28 widens to unknown
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
    tool_use_id: Annotated[str, Field(alias="toolUseId")]
    """Must match the `id` of an earlier `ToolUseContent`."""
    type: Literal["tool_result"]


class CallToolResult(WireModel):
    """The server's response to a tool call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    content: list[ContentBlock]
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """Tool errors should set this true (not raise a protocol error). Default: false."""
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None


ClientNotification: TypeAlias = (
    CancelledNotification
    | InitializedNotification
    | ProgressNotification
    | TaskStatusNotification
    | RootsListChangedNotification
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
    | GetTaskRequest
    | GetTaskPayloadRequest
    | CancelTaskRequest
    | ListTasksRequest
    | SetLevelRequest
    | CompleteRequest
)


class ElicitRequest(WireModel):
    """A request from the server to elicit additional information from the user."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["elicitation/create"]
    params: ElicitRequestParams


class GetPromptResult(WireModel):
    """The server's response to a prompts/get request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    description: str | None = None
    messages: list[PromptMessage]


SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent


ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | TaskStatusNotification
    | LoggingMessageNotification
    | ElicitationCompleteNotification
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
    | GetTaskResult
    | GetTaskPayloadResult
    | CancelTaskResult
    | ListTasksResult
    | CompleteResult
)


class CreateMessageResult(WireModel):
    """The client's response to a sampling/createMessage request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    model: str
    role: Role
    stop_reason: Annotated[str | None, Field(alias="stopReason")] = None
    """Standard values: "endTurn", "stopSequence", "maxTokens", "toolUse"; open string."""


class SamplingMessage(WireModel):
    """A message issued to or received from an LLM API."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    role: Role


ClientResult: TypeAlias = (
    Result
    | GetTaskResult
    | GetTaskPayloadResult
    | CancelTaskResult
    | ListTasksResult
    | CreateMessageResult
    | ListRootsResult
    | ElicitResult
)


class CreateMessageRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """Default "none"; "thisServer"/"allServers" are soft-deprecated."""
    max_tokens: Annotated[int, Field(alias="maxTokens")]
    messages: list[SamplingMessage]
    metadata: dict[str, Any] | None = None
    """Provider-specific passthrough."""
    model_preferences: Annotated[ModelPreferences | None, Field(alias="modelPreferences")] = None
    stop_sequences: Annotated[list[str] | None, Field(alias="stopSequences")] = None
    system_prompt: Annotated[str | None, Field(alias="systemPrompt")] = None
    task: TaskMetadata | None = None
    """If set, run as a task and return `CreateTaskResult` immediately."""
    temperature: float | None = None
    tool_choice: Annotated[ToolChoice | None, Field(alias="toolChoice")] = None
    tools: list[Tool] | None = None


class CreateMessageRequest(WireModel):
    """A request from the server to sample an LLM via the client."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


ServerRequest: TypeAlias = (
    PingRequest
    | GetTaskRequest
    | GetTaskPayloadRequest
    | CancelTaskRequest
    | ListTasksRequest
    | CreateMessageRequest
    | ListRootsRequest
    | ElicitRequest
)
