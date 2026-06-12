"""Wire-shape models for MCP protocol version 2025-11-25 — not user-facing API.

Defines only what this revision added or changed relative to 2025-06-18;
everything else is imported from the version module that last defined it, so
every import line names the module where a model is defined.
``REMOVED_FROM_PREVIOUS_VERSION`` lists the names 2025-06-18 defined that
this revision dropped.

Consumed by ``mcp.types.wire``: ``serialize_for`` re-validates each outbound
monolith dump through the negotiated version's models, importing the version
module lazily on first boundary use (never at ``import mcp.types``).

Initially generated from the pinned 2025-11-25 schema (spec commit
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
    CompleteResult,
    Cursor,
    EmptyResult,
    Error,
    LoggingLevel,
    Meta,
    ModelHint,
    ModelPreferences,
    NotificationParams,
    PaginatedResult,
    ProgressToken,
    Prompts,
    RequestId,
    RequestParams,
    Resources,
    Result,
    Role,
    Roots,
)

# Unchanged since 2025-03-26:
from mcp.types.v2025_03_26 import (
    ToolAnnotations,
)

# Unchanged since 2025-06-18:
from mcp.types.v2025_06_18 import (
    Annotations,
    AudioContent,
    BaseMetadata,
    BlobResourceContents,
    BooleanSchema,
    Context,
    EmbeddedResource,
    ImageContent,
    ListRootsResult,
    PromptArgument,
    PromptReference,
    ReadResourceResult,
    ResourceContents,
    ResourceTemplateReference,
    Root,
    TextContent,
    TextResourceContents,
)

REMOVED_FROM_PREVIOUS_VERSION: Final[frozenset[str]] = frozenset(
    {
        "JSONRPCError",
    }
)

__all__ = [
    "Annotations",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "BooleanSchema",
    "CallToolRequest",
    "CallToolRequestParams",
    "CallToolResult",
    "CancelTaskRequest",
    "CancelTaskResult",
    "CancelledNotification",
    "CancelledNotificationParams",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteRequestParams",
    "CompleteResult",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageRequestParams",
    "CreateMessageResult",
    "CreateTaskResult",
    "Cursor",
    "ElicitRequest",
    "ElicitRequestFormParams",
    "ElicitRequestParams",
    "ElicitRequestURLParams",
    "ElicitResult",
    "ElicitationCompleteNotification",
    "EmbeddedResource",
    "EmptyResult",
    "EnumSchema",
    "Error",
    "GetPromptRequest",
    "GetPromptRequestParams",
    "GetPromptResult",
    "GetTaskPayloadRequest",
    "GetTaskPayloadResult",
    "GetTaskRequest",
    "GetTaskResult",
    "Icon",
    "Icons",
    "ImageContent",
    "Implementation",
    "InitializeRequest",
    "InitializeRequestParams",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCErrorResponse",
    "JSONRPCMessage",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCResultResponse",
    "LegacyTitledEnumSchema",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourceTemplatesRequest",
    "ListResourceTemplatesResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListRootsRequest",
    "ListRootsResult",
    "ListTasksRequest",
    "ListTasksResult",
    "ListToolsRequest",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "LoggingMessageNotificationParams",
    "ModelHint",
    "ModelPreferences",
    "MultiSelectEnumSchema",
    "Notification",
    "NotificationParams",
    "NumberSchema",
    "PaginatedRequest",
    "PaginatedRequestParams",
    "PaginatedResult",
    "PingRequest",
    "PrimitiveSchemaDefinition",
    "ProgressNotification",
    "ProgressNotificationParams",
    "ProgressToken",
    "Prompt",
    "PromptArgument",
    "PromptListChangedNotification",
    "PromptMessage",
    "PromptReference",
    "ReadResourceRequest",
    "ReadResourceRequestParams",
    "ReadResourceResult",
    "RelatedTaskMetadata",
    "Request",
    "RequestId",
    "RequestParams",
    "Resource",
    "ResourceContents",
    "ResourceLink",
    "ResourceListChangedNotification",
    "ResourceRequestParams",
    "ResourceTemplate",
    "ResourceTemplateReference",
    "ResourceUpdatedNotification",
    "ResourceUpdatedNotificationParams",
    "Result",
    "Role",
    "Root",
    "RootsListChangedNotification",
    "SamplingMessage",
    "SamplingMessageContentBlock",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "SetLevelRequest",
    "SetLevelRequestParams",
    "SingleSelectEnumSchema",
    "StringSchema",
    "SubscribeRequest",
    "SubscribeRequestParams",
    "Task",
    "TaskAugmentedRequestParams",
    "TaskMetadata",
    "TaskStatus",
    "TaskStatusNotification",
    "TaskStatusNotificationParams",
    "TextContent",
    "TextResourceContents",
    "TitledMultiSelectEnumSchema",
    "TitledSingleSelectEnumSchema",
    "Tool",
    "ToolAnnotations",
    "ToolChoice",
    "ToolExecution",
    "ToolListChangedNotification",
    "ToolResultContent",
    "ToolUseContent",
    "URLElicitationRequiredError",
    "UnsubscribeRequest",
    "UnsubscribeRequestParams",
    "UntitledMultiSelectEnumSchema",
    "UntitledSingleSelectEnumSchema",
]

# --- New in 2025-11-25 ---


class CancelTaskRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to cancel.
    """


class Elicitation(WireModel):
    """Present if the client supports elicitation from the server."""

    form: dict[str, Any] | None = None
    url: dict[str, Any] | None = None


class Sampling(WireModel):
    """Present if the client supports sampling from an LLM."""

    context: dict[str, Any] | None = None
    """
    Whether the client supports context inclusion via includeContext parameter.
    If not declared, servers SHOULD only use `includeContext: "none"` (or omit it).
    """
    tools: dict[str, Any] | None = None
    """
    Whether the client supports tool use via tools and toolChoice parameters.
    """


class Elicitation1(WireModel):
    """Task support for elicitation-related requests."""

    create: dict[str, Any] | None = None
    """
    Whether the client supports task-augmented elicitation/create requests.
    """


class Sampling1(WireModel):
    """Task support for sampling-related requests."""

    create_message: Annotated[dict[str, Any] | None, Field(alias="createMessage")] = None
    """
    Whether the client supports task-augmented sampling/createMessage requests.
    """


class Requests(WireModel):
    """Specifies which request types can be augmented with tasks."""

    elicitation: Elicitation1 | None = None
    """
    Task support for elicitation-related requests.
    """
    sampling: Sampling1 | None = None
    """
    Task support for sampling-related requests.
    """


class Tasks(WireModel):
    """Present if the client supports task-augmented requests."""

    cancel: dict[str, Any] | None = None
    """
    Whether this client supports tasks/cancel.
    """
    list: dict[str, Any] | None = None
    """
    Whether this client supports tasks/list.
    """
    requests: Requests | None = None
    """
    Specifies which request types can be augmented with tasks.
    """


class ElicitationCompleteNotificationParams(WireModel):
    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """
    The ID of the elicitation that completed.
    """


class ElicitationCompleteNotification(WireModel):
    """An optional notification from the server to the client, informing it of a completion of a out-of-band
    elicitation request.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/elicitation/complete"]
    params: ElicitationCompleteNotificationParams


class GetTaskPayloadRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to retrieve results for.
    """


class GetTaskPayloadResult(WireModel):
    """The response to a tasks/result request.
    The structure matches the result type of the original request.
    For example, a tools/call task would return the CallToolResult structure.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """


class GetTaskRequestParams(WireModel):
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to query.
    """


class Icon(WireModel):
    """An optionally-sized icon that can be displayed in a user interface."""

    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    Optional MIME type override if the source MIME type is missing or generic.
    For example: `"image/png"`, `"image/jpeg"`, or `"image/svg+xml"`.
    """
    sizes: list[str] | None = None
    """
    Optional array of strings that specify sizes at which the icon can be used.
    Each string should be in WxH format (e.g., `"48x48"`, `"96x96"`) or `"any"` for scalable formats like SVG.

    If not provided, the client should assume that the icon can be used at any size.
    """
    src: str
    """
    A standard URI pointing to an icon resource. May be an HTTP/HTTPS URL or a
    `data:` URI with Base64-encoded image data.

    Consumers SHOULD takes steps to ensure URLs serving icons are from the
    same domain as the client/server or a trusted domain.

    Consumers SHOULD take appropriate precautions when consuming SVGs as they can contain
    executable JavaScript.
    """
    theme: Literal["dark", "light"] | None = None
    """
    Optional specifier for the theme this icon is designed for. `light` indicates
    the icon is designed to be used with a light background, and `dark` indicates
    the icon is designed to be used with a dark background.

    If not provided, the client should assume the icon can be used with any theme.
    """


class Icons(WireModel):
    """Base interface to add `icons` property."""

    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
    """


class LegacyTitledEnumSchema(WireModel):
    """Use TitledSingleSelectEnumSchema instead.
    This interface will be removed in a future version.
    """

    default: str | None = None
    description: str | None = None
    enum: list[str]
    enum_names: Annotated[list[str] | None, Field(alias="enumNames")] = None
    """
    (Legacy) Display names for enum values.
    Non-standard according to JSON schema 2020-12.
    """
    title: str | None = None
    type: Literal["string"]


class RelatedTaskMetadata(WireModel):
    """Metadata for associating messages with a task.
    Include this in the `_meta` field under the key `io.modelcontextprotocol/related-task`.
    """

    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier this message is associated with.
    """


class ResourceRequestParams(WireModel):
    """Common parameters when working with resources."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class Requests1(WireModel):
    """Specifies which request types can be augmented with tasks."""

    tools: Tools | None = None
    """
    Task support for tool-related requests.
    """


class Tasks1(WireModel):
    """Present if the server supports task-augmented requests."""

    cancel: dict[str, Any] | None = None
    """
    Whether this server supports tasks/cancel.
    """
    list: dict[str, Any] | None = None
    """
    Whether this server supports tasks/list.
    """
    requests: Requests1 | None = None
    """
    Specifies which request types can be augmented with tasks.
    """


class Tools1(WireModel):
    """Present if the server offers any tools to call."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the tool list.
    """


class TaskMetadata(WireModel):
    """Metadata for augmenting a request with task execution.
    Include this in the `task` field of the request parameters.
    """

    ttl: int | None = None
    """
    Requested duration in milliseconds to retain task from creation.
    """


class AnyOfItem(WireModel):
    const: str
    """
    The constant enum value.
    """
    title: str
    """
    Display title for this option.
    """


class Items(WireModel):
    """Schema for array items with enum options and display labels."""

    any_of: Annotated[list[AnyOfItem], Field(alias="anyOf")]
    """
    Array of enum options with values and display labels.
    """


class TitledMultiSelectEnumSchema(WireModel):
    """Schema for multiple-selection enumeration with display titles for each option."""

    default: list[str] | None = None
    """
    Optional default value.
    """
    description: str | None = None
    """
    Optional description for the enum field.
    """
    items: Items
    """
    Schema for array items with enum options and display labels.
    """
    max_items: Annotated[int | None, Field(alias="maxItems")] = None
    """
    Maximum number of items to select.
    """
    min_items: Annotated[int | None, Field(alias="minItems")] = None
    """
    Minimum number of items to select.
    """
    title: str | None = None
    """
    Optional title for the enum field.
    """
    type: Literal["array"]


class OneOfItem(WireModel):
    const: str
    """
    The enum value.
    """
    title: str
    """
    Display label for this option.
    """


class TitledSingleSelectEnumSchema(WireModel):
    """Schema for single-selection enumeration with display titles for each option."""

    default: str | None = None
    """
    Optional default value.
    """
    description: str | None = None
    """
    Optional description for the enum field.
    """
    one_of: Annotated[list[OneOfItem], Field(alias="oneOf")]
    """
    Array of enum options with values and display labels.
    """
    title: str | None = None
    """
    Optional title for the enum field.
    """
    type: Literal["string"]


class ToolChoice(WireModel):
    """Controls tool selection behavior for sampling requests."""

    mode: Literal["auto", "none", "required"] | None = None
    """
    Controls the tool use ability of the model:
    - "auto": Model decides whether to use tools (default)
    - "required": Model MUST use at least one tool before completing
    - "none": Model MUST NOT use any tools
    """


class ToolExecution(WireModel):
    """Execution-related properties for a tool."""

    task_support: Annotated[Literal["forbidden", "optional", "required"] | None, Field(alias="taskSupport")] = None
    """
    Indicates whether this tool supports task-augmented execution.
    This allows clients to handle long-running operations through polling
    the task system.

    - "forbidden": Tool does not support task-augmented execution (default when absent)
    - "optional": Tool may support task-augmented execution
    - "required": Tool requires task-augmented execution

    Default: "forbidden"
    """


class ToolUseContent(WireModel):
    """A request from the assistant to call a tool."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    Optional metadata about the tool use. Clients SHOULD preserve this field when
    including tool uses in subsequent sampling requests to enable caching optimizations.

    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    id: str
    """
    A unique identifier for this tool use.

    This ID is used to match tool results to their corresponding tool uses.
    """
    input: dict[str, Any]
    """
    The arguments to pass to the tool, conforming to the tool's input schema.
    """
    name: str
    """
    The name of the tool to call.
    """
    type: Literal["tool_use"]


class Items1(WireModel):
    """Schema for the array items."""

    enum: list[str]
    """
    Array of enum values to choose from.
    """
    type: Literal["string"]


class UntitledMultiSelectEnumSchema(WireModel):
    """Schema for multiple-selection enumeration without display titles for options."""

    default: list[str] | None = None
    """
    Optional default value.
    """
    description: str | None = None
    """
    Optional description for the enum field.
    """
    items: Items1
    """
    Schema for the array items.
    """
    max_items: Annotated[int | None, Field(alias="maxItems")] = None
    """
    Maximum number of items to select.
    """
    min_items: Annotated[int | None, Field(alias="minItems")] = None
    """
    Minimum number of items to select.
    """
    title: str | None = None
    """
    Optional title for the enum field.
    """
    type: Literal["array"]


class UntitledSingleSelectEnumSchema(WireModel):
    """Schema for single-selection enumeration without display titles for options."""

    default: str | None = None
    """
    Optional default value.
    """
    description: str | None = None
    """
    Optional description for the enum field.
    """
    enum: list[str]
    """
    Array of enum values to choose from.
    """
    title: str | None = None
    """
    Optional title for the enum field.
    """
    type: Literal["string"]


class CancelTaskRequest(WireModel):
    """A request to cancel a task."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/cancel"]
    params: CancelTaskRequestParams


class ElicitRequestURLParams(WireModel):
    """The parameters for a request to elicit information from the user via a URL in the client."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """
    The ID of the elicitation, which must be unique within the context of the server.
    The client MUST treat this ID as an opaque value.
    """
    message: str
    """
    The message to present to the user explaining why the interaction is needed.
    """
    mode: Literal["url"]
    """
    The elicitation mode.
    """
    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """
    url: str
    """
    The URL that the user should navigate to.
    """


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


class JSONRPCErrorResponse(WireModel):
    """A response to a request that indicates an error occurred."""

    error: Error
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class JSONRPCResultResponse(WireModel):
    """A successful (non-error) response to a request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class Task(WireModel):
    """Data associated with a task."""

    created_at: Annotated[str, Field(alias="createdAt")]
    """
    ISO 8601 timestamp when the task was created.
    """
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """
    ISO 8601 timestamp when the task was last updated.
    """
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """
    Suggested polling interval in milliseconds.
    """
    status: TaskStatus
    """
    Current task state.
    """
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    """
    Optional human-readable message describing the current task state.
    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier.
    """
    ttl: int | None
    """
    Actual retention duration from creation in milliseconds, null for unlimited.
    """


class TaskAugmentedRequestParams(WireModel):
    """Common params for any task-augmented request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """


class TaskStatusNotificationParams(WireModel):
    """Parameters for a `notifications/tasks/status` notification."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    created_at: Annotated[str, Field(alias="createdAt")]
    """
    ISO 8601 timestamp when the task was created.
    """
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """
    ISO 8601 timestamp when the task was last updated.
    """
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """
    Suggested polling interval in milliseconds.
    """
    status: TaskStatus
    """
    Current task state.
    """
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    """
    Optional human-readable message describing the current task state.
    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier.
    """
    ttl: int | None
    """
    Actual retention duration from creation in milliseconds, null for unlimited.
    """


class Data(WireModel):
    """Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """

    elicitations: list[ElicitRequestURLParams]


class Error1(WireModel):
    code: Literal[-32042]
    """
    The error type that occurred.
    """
    data: Data
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """
    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single sentence.
    """


class URLElicitationRequiredError(WireModel):
    """An error response that indicates that the server requires the client to provide additional information via an
    elicitation request.
    """

    error: Error1
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class CancelTaskResult(WireModel):
    """The response to a tasks/cancel request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    created_at: Annotated[str, Field(alias="createdAt")]
    """
    ISO 8601 timestamp when the task was created.
    """
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """
    ISO 8601 timestamp when the task was last updated.
    """
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """
    Suggested polling interval in milliseconds.
    """
    status: TaskStatus
    """
    Current task state.
    """
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    """
    Optional human-readable message describing the current task state.
    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier.
    """
    ttl: int | None
    """
    Actual retention duration from creation in milliseconds, null for unlimited.
    """


class CreateTaskResult(WireModel):
    """A response to a task-augmented request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    task: Task


class ElicitRequestFormParams(WireModel):
    """The parameters for a request to elicit non-sensitive information from the user via a form in the client."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    message: str
    """
    The message to present to the user describing what information is being requested.
    """
    mode: Literal["form"] = "form"
    """
    The elicitation mode.
    """
    requested_schema: Annotated[RequestedSchema, Field(alias="requestedSchema")]
    """
    A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """
    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """


class GetTaskResult(WireModel):
    """The response to a tasks/get request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    created_at: Annotated[str, Field(alias="createdAt")]
    """
    ISO 8601 timestamp when the task was created.
    """
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    """
    ISO 8601 timestamp when the task was last updated.
    """
    poll_interval: Annotated[int | None, Field(alias="pollInterval")] = None
    """
    Suggested polling interval in milliseconds.
    """
    status: TaskStatus
    """
    Current task state.
    """
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    """
    Optional human-readable message describing the current task state.
    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier.
    """
    ttl: int | None
    """
    Actual retention duration from creation in milliseconds, null for unlimited.
    """


class ListTasksRequest(WireModel):
    """A request to retrieve a list of tasks."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/list"]
    params: PaginatedRequestParams | None = None


class ListTasksResult(WireModel):
    """The response to a tasks/list request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    tasks: list[Task]


class TaskStatusNotification(WireModel):
    """An optional notification from the receiver to the requestor, informing them that a task's status has changed.
    Receivers are not required to send these notifications.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tasks/status"]
    params: TaskStatusNotificationParams


class ToolResultContent(WireModel):
    """The result of a tool use, provided by the user back to the assistant."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    Optional metadata about the tool result. Clients SHOULD preserve this field when
    including tool results in subsequent sampling requests to enable caching optimizations.

    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    content: list[ContentBlock]
    """
    The unstructured result content of the tool use.

    This has the same format as CallToolResult.content and can include text, images,
    audio, resource links, and embedded resources.
    """
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """
    Whether the tool use resulted in an error.

    If true, the content typically describes the error that occurred.
    Default: false
    """
    structured_content: Annotated[Any | None, Field(alias="structuredContent")] = None
    """
    An optional structured result object.

    If the tool defined an outputSchema, this SHOULD conform to that schema.
    """
    tool_use_id: Annotated[str, Field(alias="toolUseId")]
    """
    The ID of the tool use this result corresponds to.

    This MUST match the ID from a previous ToolUseContent.
    """
    type: Literal["tool_result"]


# --- Changed in 2025-11-25 ---


class ClientCapabilities(WireModel):
    """Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any client can define its own, additional capabilities.
    """

    elicitation: Elicitation | None = None
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
    sampling: Sampling | None = None
    """
    Present if the client supports sampling from an LLM.
    """
    tasks: Tasks | None = None
    """
    Present if the client supports task-augmented requests.
    """


class ElicitResult(WireModel):
    """The client's response to an elicitation request."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    action: Literal["accept", "cancel", "decline"]
    """
    The user action in response to the elicitation.
    - "accept": User submitted the form/confirmed the action
    - "decline": User explicitly decline the action
    - "cancel": User dismissed without making an explicit choice
    """
    # Deliberate deviation from the pinned schema.json, which renders the
    # value union's number arm as "integer" — its schema.ts source types form
    # answers string | number | boolean | string[], so fractional answers are
    # legal wire values. The float arm follows schema.ts; the generated
    # oracle keeps the rendering verbatim and the surface test pins this
    # annotation separately.
    content: dict[str, list[str] | str | int | float | bool] | None = None
    """
    The submitted form data, only present when action is "accept" and mode was "form".
    Contains values matching the requested schema.
    Omitted for out-of-band mode responses.
    """


class Implementation(WireModel):
    """Describes the MCP implementation."""

    description: str | None = None
    """
    An optional human-readable description of what this implementation does.

    This can be used by clients or servers to provide context about their purpose
    and capabilities. For example, a server might describe the types of resources
    or tools it provides, while a client might describe its intended use case.
    """
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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
    version: str
    website_url: Annotated[str | None, Field(alias="websiteUrl")] = None
    """
    An optional URL of the website for this implementation.
    """


class JSONRPCNotification(WireModel):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class LoggingMessageNotificationParams(WireModel):
    """Parameters for a `notifications/message` notification."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
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


class Notification(WireModel):
    method: str
    params: dict[str, Any] | None = None


class NumberSchema(WireModel):
    # Deliberate deviation from the pinned schema.json, which renders the
    # default and the bounds as "integer" — schema.ts types them number
    # (JSON Schema minimum/maximum/default are numbers; the schema describes
    # number fields too). The float arms follow schema.ts; the generated
    # oracle keeps the rendering verbatim and the surface test pins these
    # annotations separately.
    default: int | float | None = None
    description: str | None = None
    maximum: int | float | None = None
    minimum: int | float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class PromptListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of prompts it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class ReadResourceRequestParams(WireModel):
    """Parameters for a `resources/read` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class Request(WireModel):
    method: str
    params: dict[str, Any] | None = None


class ResourceListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of resources it can read
    from has changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class ResourceUpdatedNotificationParams(WireModel):
    """Parameters for a `notifications/resources/updated` notification."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource that has been updated. This might be a sub-resource of the one that the client actually
    subscribed to.
    """


class RootsListChangedNotification(WireModel):
    """A notification from the client to the server, informing it that the list of roots has changed.
    This notification should be sent whenever the client adds, removes, or modifies any root.
    The server should then request an updated list of roots using the ListRootsRequest.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/roots/list_changed"]
    params: NotificationParams | None = None


class Tools(WireModel):
    """Task support for tool-related requests."""

    call: dict[str, Any] | None = None
    """
    Whether the server supports task-augmented tools/call requests.
    """


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
    tasks: Tasks1 | None = None
    """
    Present if the server supports task-augmented requests.
    """
    tools: Tools1 | None = None
    """
    Present if the server offers any tools to call.
    """


class SetLevelRequestParams(WireModel):
    """Parameters for a `logging/setLevel` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    level: LoggingLevel
    """
    The level of logging that the client wants to receive from the server. The server should send all logs at this level
    and higher (i.e., more severe) to the client as notifications/message.
    """


class StringSchema(WireModel):
    default: str | None = None
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class SubscribeRequestParams(WireModel):
    """Parameters for a `resources/subscribe` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class InputSchema(WireModel):
    """A JSON Schema object defining the expected parameters for the tool."""

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class OutputSchema(WireModel):
    """An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult.

    Defaults to JSON Schema 2020-12 when no explicit $schema is provided.
    Currently restricted to type: "object" at the root level.
    """

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class ToolListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of tools it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


class UnsubscribeRequestParams(WireModel):
    """Parameters for a `resources/unsubscribe` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class CallToolRequestParams(WireModel):
    """Parameters for a `tools/call` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    arguments: dict[str, Any] | None = None
    """
    Arguments to use for the tool call.
    """
    name: str
    """
    The name of the tool.
    """
    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """


class CancelledNotificationParams(WireModel):
    """Parameters for a `notifications/cancelled` notification."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    reason: str | None = None
    """
    An optional string describing the reason for the cancellation. This MAY be logged or presented to the user.
    """
    request_id: Annotated[RequestId | None, Field(alias="requestId")] = None
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    This MUST be provided for cancelling non-task requests.
    This MUST NOT be used for cancelling tasks (use the `tasks/cancel` request instead).
    """


class CompleteRequestParams(WireModel):
    """Parameters for a `completion/complete` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    argument: Argument
    """
    The argument's information
    """
    context: Context | None = None
    """
    Additional, optional context for completions
    """
    ref: PromptReference | ResourceTemplateReference


class GetPromptRequestParams(WireModel):
    """Parameters for a `prompts/get` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    arguments: dict[str, str] | None = None
    """
    Arguments to use for templating the prompt.
    """
    name: str
    """
    The name of the prompt or prompt template.
    """


class InitializeRequestParams(WireModel):
    """Parameters for an `initialize` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The latest version of the Model Context Protocol that the client supports. The client MAY decide to support older
    versions as well.
    """


class InitializeResult(WireModel):
    """After receiving an initialize request from the client, the server sends this response."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class InitializedNotification(WireModel):
    """This notification is sent from the client to the server after initialization has finished."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/initialized"]
    params: NotificationParams | None = None


class JSONRPCRequest(WireModel):
    """A request that expects a response."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class ListRootsRequest(WireModel):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["roots/list"]
    params: RequestParams | None = None


class LoggingMessageNotification(WireModel):
    """JSONRPCNotification of a log message passed from server to client. If no logging/setLevel request has been
    sent from the client, the server MAY decide which messages to send automatically.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


class PaginatedRequestParams(WireModel):
    """Common parameters for paginated requests."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class PingRequest(WireModel):
    """A ping, issued by either the server or the client, to check that the other party is still alive. The receiver
    must promptly respond, or else may be disconnected.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["ping"]
    params: RequestParams | None = None


class ProgressNotificationParams(WireModel):
    """Parameters for a `notifications/progress` notification."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
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


class Prompt(WireModel):
    """A prompt or prompt template that the server offers."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    arguments: list[PromptArgument] | None = None
    """
    A list of arguments to use for templating the prompt.
    """
    description: str | None = None
    """
    An optional description of what this prompt provides
    """
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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


class ReadResourceRequest(WireModel):
    """Sent from the client to the server, to read a specific resource URI."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class Resource(WireModel):
    """A known resource that the server is capable of reading."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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


class ResourceUpdatedNotification(WireModel):
    """A notification from the server to the client, informing it that a resource has changed and may need to be read
    again. This should only be sent if the client previously sent a resources/subscribe request.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class SetLevelRequest(WireModel):
    """A request from the client to the server, to enable or adjust logging."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["logging/setLevel"]
    params: SetLevelRequestParams


class SubscribeRequest(WireModel):
    """Sent from the client to request resources/updated notifications from the server whenever a particular resource
    changes.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/subscribe"]
    params: SubscribeRequestParams


class Tool(WireModel):
    """Definition for a tool the client can call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    execution: ToolExecution | None = None
    """
    Execution-related properties for this tool.
    """
    icons: list[Icon] | None = None
    """
    Optional set of sized icons that the client can display in a user interface.

    Clients that support rendering icons MUST support at least the following MIME types:
    - `image/png` - PNG images (safe, universal compatibility)
    - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)

    Clients that support rendering icons SHOULD also support:
    - `image/svg+xml` - SVG images (scalable but requires security precautions)
    - `image/webp` - WebP images (modern, efficient format)
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

    Defaults to JSON Schema 2020-12 when no explicit $schema is provided.
    Currently restricted to type: "object" at the root level.
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class UnsubscribeRequest(WireModel):
    """Sent from the client to request cancellation of resources/updated notifications from the server. This should
    follow a previous resources/subscribe request.
    """

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


class CancelledNotification(WireModel):
    """This notification can be sent by either side to indicate that it is cancelling a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it is always possible that this
    notification MAY arrive after the request has already finished.

    This notification indicates that the result will be unused, so any associated processing SHOULD cease.

    A client MUST NOT attempt to cancel its `initialize` request.

    For task cancellation, use the `tasks/cancel` request instead of this notification.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


class CompleteRequest(WireModel):
    """A request from the client to the server, to ask for completion options."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["completion/complete"]
    params: CompleteRequestParams


class RequestedSchema(WireModel):
    """A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class GetPromptRequest(WireModel):
    """Used by the client to get a prompt provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class InitializeRequest(WireModel):
    """This request is sent from the client to the server when it first connects, asking it to begin initialization."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["initialize"]
    params: InitializeRequestParams


class ListPromptsRequest(WireModel):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/list"]
    params: PaginatedRequestParams | None = None


class ListPromptsResult(WireModel):
    """The server's response to a prompts/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    prompts: list[Prompt]


class ListResourceTemplatesRequest(WireModel):
    """Sent from the client to request a list of resource templates the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/templates/list"]
    params: PaginatedRequestParams | None = None


class ListResourceTemplatesResult(WireModel):
    """The server's response to a resources/templates/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]


class ListResourcesRequest(WireModel):
    """Sent from the client to request a list of resources the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/list"]
    params: PaginatedRequestParams | None = None


class ListResourcesResult(WireModel):
    """The server's response to a resources/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resources: list[Resource]


class ListToolsRequest(WireModel):
    """Sent from the client to request a list of tools the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/list"]
    params: PaginatedRequestParams | None = None


class ListToolsResult(WireModel):
    """The server's response to a tools/list request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    tools: list[Tool]


class PaginatedRequest(WireModel):
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: PaginatedRequestParams | None = None


class ProgressNotification(WireModel):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class PromptMessage(WireModel):
    """Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    content: ContentBlock
    role: Role


class CallToolResult(WireModel):
    """The server's response to a tool call."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class ElicitRequest(WireModel):
    """A request from the server to elicit additional information from the user via the client."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["elicitation/create"]
    params: ElicitRequestParams


class GetPromptResult(WireModel):
    """The server's response to a prompts/get request from the client."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    description: str | None = None
    """
    An optional description for the prompt.
    """
    messages: list[PromptMessage]


class CreateMessageResult(WireModel):
    """The client's response to a sampling/createMessage request from the server.
    The client should inform the user before returning the sampled message, to allow them
    to inspect the response (human in the loop) and decide whether to allow the server to see it.
    """

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    model: str
    """
    The name of the model that generated the message.
    """
    role: Role
    stop_reason: Annotated[str | None, Field(alias="stopReason")] = None
    """
    The reason why sampling stopped, if known.

    Standard values:
    - "endTurn": Natural end of the assistant's turn
    - "stopSequence": A stop sequence was encountered
    - "maxTokens": Maximum token limit was reached
    - "toolUse": The model wants to use one or more tools

    This field is an open string to allow for provider-specific stop reasons.
    """


class SamplingMessage(WireModel):
    """Describes a message issued to or received from an LLM API."""

    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    role: Role


class CreateMessageRequestParams(WireModel):
    """Parameters for a `sampling/createMessage` request."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """
    A request to include context from one or more MCP servers (including the caller), to be attached to the prompt.
    The client MAY ignore this request.

    Default is "none". Values "thisServer" and "allServers" are soft-deprecated. Servers SHOULD only use these values if
    the client
    declares ClientCapabilities.sampling.context. These values may be removed in future spec releases.
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
    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """
    temperature: float | None = None
    tool_choice: Annotated[ToolChoice | None, Field(alias="toolChoice")] = None
    """
    Controls how the model uses tools.
    The client MUST return an error if this field is provided but ClientCapabilities.sampling.tools is not declared.
    Default is `{ mode: "auto" }`.
    """
    tools: list[Tool] | None = None
    """
    Tools that the model may use during generation.
    The client MUST return an error if this field is provided but ClientCapabilities.sampling.tools is not declared.
    """


class CreateMessageRequest(WireModel):
    """A request from the server to sample an LLM via the client. The client has full discretion over which model to
    select. The client should also inform the user before beginning sampling, to allow them to inspect the request
    (human in the loop) and decide whether to approve it.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


# --- Aliases new or changed in 2025-11-25 ---
# (defined last: an alias right-hand side evaluates its referents at import)

TaskStatus: TypeAlias = Literal["cancelled", "completed", "failed", "input_required", "working"]

EnumSchema: TypeAlias = (
    UntitledSingleSelectEnumSchema
    | TitledSingleSelectEnumSchema
    | UntitledMultiSelectEnumSchema
    | TitledMultiSelectEnumSchema
    | LegacyTitledEnumSchema
)

MultiSelectEnumSchema: TypeAlias = UntitledMultiSelectEnumSchema | TitledMultiSelectEnumSchema

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

SingleSelectEnumSchema: TypeAlias = UntitledSingleSelectEnumSchema | TitledSingleSelectEnumSchema

ContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource

ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams

JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse

JSONRPCResponse: TypeAlias = JSONRPCResultResponse | JSONRPCErrorResponse

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

Requests1.model_rebuild()
Task.model_rebuild()
TaskStatusNotificationParams.model_rebuild()
CancelTaskResult.model_rebuild()
ElicitRequestFormParams.model_rebuild()
GetTaskResult.model_rebuild()
ListTasksRequest.model_rebuild()
ToolResultContent.model_rebuild()
RequestedSchema.model_rebuild()
PromptMessage.model_rebuild()
CallToolResult.model_rebuild()
ElicitRequest.model_rebuild()
CreateMessageResult.model_rebuild()
SamplingMessage.model_rebuild()
