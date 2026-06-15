"""Internal wire-shape models for protocol 2026-07-28. Not part of the public API.

Schema-exact validators that the wire-method maps in `mcp.types.methods` point
inbound 2026-07-28 validation at. Generated from schema/draft/schema.json
@ 6d441518de8a9d5adbab0b10a76a667a63f90665 and hand-maintained against that
revision. Models use `extra="ignore"` (unknown keys accepted and dropped) unless
commented otherwise; see `mcp.types._wire_base`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field
from typing_extensions import TypeAliasType

from mcp.types._wire_base import OpenWireModel, WireModel

# Deviates from schema.json (renders only string|integer|boolean); follows
# schema.ts, which defines all six JSON types, so floats and null validate.
JSONValue = TypeAliasType("JSONValue", "JSONObject | list[JSONValue] | str | int | float | bool | None")


JSONObject = TypeAliasType("JSONObject", dict[str, "JSONValue"])


class BaseMetadata(WireModel):
    """Base interface for metadata with name (identifier) and title (display name)."""

    name: str
    """Programmatic identifier; also the display fallback when `title` is absent."""
    title: str | None = None
    """Human-readable display name."""


class BooleanSchema(WireModel):
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


class Argument(WireModel):
    """The argument being completed."""

    name: str
    value: str
    """Value to use for completion matching."""


class Context(WireModel):
    """Additional context for completions."""

    arguments: dict[str, str] | None = None
    """Already-resolved variables in a URI template or prompt."""


class Completion(WireModel):
    has_more: Annotated[bool | None, Field(alias="hasMore")] = None
    """Whether more options exist beyond this response, even if `total` is unknown."""
    total: int | None = None
    """Total options available; can exceed `len(values)`."""
    values: Annotated[list[str], Field(max_length=100)]
    """Completion values; at most 100 items."""


Cursor: TypeAlias = str


class ElicitRequestURLParams(WireModel):
    """Parameters for a URL-mode `elicitation/create` request."""

    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """Server-unique opaque ID for this elicitation."""
    message: str
    mode: Literal["url"]
    url: str
    """URL the user should navigate to."""


class ElicitResult(WireModel):
    """Client's result for an `elicitation/create` request."""

    action: Literal["accept", "cancel", "decline"]
    """`accept` = submitted, `decline` = explicit no, `cancel` = dismissed."""
    # Deviates from schema.json (renders number arm as integer); follows
    # schema.ts (string|number|boolean|string[]) so float answers validate.
    content: dict[str, list[str] | str | int | float | bool] | None = None
    """Submitted form data; only present when `action == "accept"` and mode was `"form"`."""


class ElicitationCompleteNotificationParams(WireModel):
    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """ID of the elicitation that completed."""


class ElicitationCompleteNotification(WireModel):
    """Server-to-client: an out-of-band elicitation has completed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/elicitation/complete"]
    params: ElicitationCompleteNotificationParams


class Error(WireModel):
    code: int
    data: Any | None = None
    message: str


class Icon(WireModel):
    """An optionally-sized icon for display in a UI."""

    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    sizes: list[str] | None = None
    """Sizes the icon supports, each as `"WxH"` or `"any"`; absent means any size."""
    src: str
    """HTTP(S) or `data:` URI; consumers should vet origin and sandbox SVG."""
    theme: Literal["dark", "light"] | None = None
    """Background theme this icon is designed for; absent means any theme."""


class Icons(WireModel):
    """Mixin adding the `icons` property."""

    icons: list[Icon] | None = None


class Implementation(WireModel):
    """Describes an MCP implementation."""

    description: str | None = None
    icons: list[Icon] | None = None
    name: str
    title: str | None = None
    version: str
    website_url: Annotated[str | None, Field(alias="websiteUrl")] = None


class InternalError(WireModel):
    """JSON-RPC: internal error on the receiver."""

    code: Literal[-32603]
    data: Any | None = None
    message: str


class InvalidParamsError(WireModel):
    """JSON-RPC: method parameters are invalid or malformed."""

    code: Literal[-32602]
    data: Any | None = None
    message: str


class InvalidRequestError(WireModel):
    """JSON-RPC: request object does not conform to JSON-RPC 2.0."""

    code: Literal[-32600]
    data: Any | None = None
    message: str


class JSONRPCNotification(WireModel):
    """A notification, which does not expect a response."""

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class LegacyTitledEnumSchema(WireModel):
    """Deprecated; use `TitledSingleSelectEnumSchema`."""

    default: str | None = None
    description: str | None = None
    enum: list[str]
    enum_names: Annotated[list[str] | None, Field(alias="enumNames")] = None
    """Display names for enum values (non-standard for JSON Schema 2020-12)."""
    title: str | None = None
    type: Literal["string"]


LoggingLevel: TypeAlias = Literal["alert", "critical", "debug", "emergency", "error", "info", "notice", "warning"]


class MetaObject(OpenWireModel):
    """Contents of a `_meta` field; see the schema for key naming and reservation rules."""


class MethodNotFoundError(WireModel):
    """JSON-RPC: requested method does not exist or is not available."""

    code: Literal[-32601]
    data: Any | None = None
    message: str


class ModelHint(WireModel):
    """Hints for model selection; undeclared keys are client-defined."""

    name: str | None = None
    """Model-name substring hint; the client may also map it to an equivalent from another provider."""


class ModelPreferences(WireModel):
    """Server's advisory preferences for model selection during sampling."""

    cost_priority: Annotated[float | None, Field(alias="costPriority", ge=0.0, le=1.0)] = None
    hints: list[ModelHint] | None = None
    """Evaluated in order (first match wins); should outweigh the numeric priorities."""
    intelligence_priority: Annotated[float | None, Field(alias="intelligencePriority", ge=0.0, le=1.0)] = None
    speed_priority: Annotated[float | None, Field(alias="speedPriority", ge=0.0, le=1.0)] = None


class Notification(WireModel):
    method: str
    params: dict[str, Any] | None = None


class NotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None


class NumberSchema(WireModel):
    default: float | None = None
    description: str | None = None
    maximum: float | None = None
    minimum: float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class PaginatedResult(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination position; if present, more results may be available."""
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""


class ParseError(WireModel):
    """JSON-RPC: invalid JSON received."""

    code: Literal[-32700]
    data: Any | None = None
    message: str


ProgressToken: TypeAlias = str | int


class PromptArgument(WireModel):
    """Describes an argument that a prompt can accept."""

    description: str | None = None
    name: str
    required: bool | None = None
    title: str | None = None


class PromptListChangedNotification(WireModel):
    """Server-to-client: the prompt list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class PromptReference(WireModel):
    """Identifies a prompt."""

    name: str
    title: str | None = None
    type: Literal["ref/prompt"]


class Request(WireModel):
    method: str
    params: dict[str, Any] | None = None


RequestId: TypeAlias = str | int


class ResourceContents(WireModel):
    """The contents of a specific resource or sub-resource."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    uri: str


class ResourceListChangedNotification(WireModel):
    """Server-to-client: the resource list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class ResourceTemplateReference(WireModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """URI or URI template of the resource."""


class ResourceUpdatedNotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    uri: str
    """URI of the updated resource; may be a sub-resource of the subscription URI."""


class Result(WireModel):
    """Common result fields."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""


ResultType: TypeAlias = str


Role: TypeAlias = Literal["assistant", "user"]


class Root(WireModel):
    """A root directory or file the server can operate on."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    name: str | None = None
    uri: str
    """Must start with `file://` for now."""


class Prompts(WireModel):
    """Present if the server offers any prompt templates."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """Whether the server supports prompt-list-changed notifications."""


class Resources(WireModel):
    """Present if the server offers any resources to read."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """Whether the server supports resource-list-changed notifications."""
    subscribe: bool | None = None
    """Whether the server supports subscribing to resource updates."""


class Tools(WireModel):
    """Present if the server offers any tools to call."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """Whether the server supports tool-list-changed notifications."""


class StringSchema(WireModel):
    default: str | None = None
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class SubscriptionFilter(WireModel):
    """Notification types a client opts in to on `subscriptions/listen`; each is opt-in."""

    # Stays open: filter contents are extensible on the wire.
    model_config = ConfigDict(
        extra="allow",
    )
    prompts_list_changed: Annotated[bool | None, Field(alias="promptsListChanged")] = None
    """Receive `notifications/prompts/list_changed`."""
    resource_subscriptions: Annotated[list[str] | None, Field(alias="resourceSubscriptions")] = None
    """Receive `notifications/resources/updated` for these resource URIs."""
    resources_list_changed: Annotated[bool | None, Field(alias="resourcesListChanged")] = None
    """Receive `notifications/resources/list_changed`."""
    tools_list_changed: Annotated[bool | None, Field(alias="toolsListChanged")] = None
    """Receive `notifications/tools/list_changed`."""


class SubscriptionsAcknowledgedNotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    notifications: SubscriptionFilter
    """Subset of requested notification types the server agreed to honor."""


class TextResourceContents(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    text: str
    uri: str


class AnyOfItem(WireModel):
    const: str
    title: str


class Items(WireModel):
    """Array-item schema with enum options and display labels."""

    any_of: Annotated[list[AnyOfItem], Field(alias="anyOf")]


class TitledMultiSelectEnumSchema(WireModel):
    """Multi-select enum schema with per-option display titles."""

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
    """Single-select enum schema with per-option display titles."""

    default: str | None = None
    description: str | None = None
    one_of: Annotated[list[OneOfItem], Field(alias="oneOf")]
    title: str | None = None
    type: Literal["string"]


class InputSchema(WireModel):
    """JSON Schema for tool parameters; root must be `type: "object"`, defaulting to 2020-12."""

    # Stays open: arbitrary JSON Schema keywords ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    type: Literal["object"]


class OutputSchema(WireModel):
    """JSON Schema for a tool's `structuredContent` output; defaults to 2020-12."""

    # Stays open: arbitrary JSON Schema keywords ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None


class ToolAnnotations(WireModel):
    """Tool hints; not guaranteed faithful, never trust from untrusted servers."""

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    """May perform destructive updates (only meaningful when not read-only); default true."""
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    """Repeat calls with same args have no additional effect; default false."""
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    """Interacts with an open world of external entities; default true."""
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    """Does not modify its environment; default false."""
    title: str | None = None


class ToolChoice(WireModel):
    """Controls tool-selection behavior for sampling requests."""

    mode: Literal["auto", "none", "required"] | None = None
    """`auto` (default) = model decides, `required` = must use a tool, `none` = must not."""


class ToolListChangedNotification(WireModel):
    """Server-to-client: the tool list has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


class ToolUseContent(WireModel):
    """A request from the assistant to call a tool."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    id: str
    """Unique ID matching this tool use to its result."""
    input: dict[str, Any]
    """Arguments conforming to the tool's input schema."""
    name: str
    type: Literal["tool_use"]


class Data1(WireModel):
    requested: str
    """Protocol version the client requested."""
    supported: list[str]
    """Protocol versions the server supports; the client should retry with one of these."""


class Error2(WireModel):
    code: Literal[-32004]
    data: Data1
    message: str


class UnsupportedProtocolVersionError(WireModel):
    """The requested protocol version is unknown or unsupported (HTTP: `400 Bad Request`)."""

    error: Error2
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class Items1(WireModel):
    """Array-item schema."""

    enum: list[str]
    type: Literal["string"]


class UntitledMultiSelectEnumSchema(WireModel):
    """Multi-select enum schema without per-option display titles."""

    default: list[str] | None = None
    description: str | None = None
    items: Items1
    max_items: Annotated[int | None, Field(alias="maxItems")] = None
    min_items: Annotated[int | None, Field(alias="minItems")] = None
    title: str | None = None
    type: Literal["array"]


class UntitledSingleSelectEnumSchema(WireModel):
    """Single-select enum schema without per-option display titles."""

    default: str | None = None
    description: str | None = None
    enum: list[str]
    title: str | None = None
    type: Literal["string"]


class Annotations(WireModel):
    """Client-facing annotations informing how objects are used or displayed."""

    audience: list[Role] | None = None
    """Intended audience(s) of this object or data."""
    last_modified: Annotated[str | None, Field(alias="lastModified")] = None
    """ISO 8601 timestamp of last modification."""
    priority: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    """Importance for operating the server: 1 = effectively required, 0 = entirely optional."""


class AudioContent(WireModel):
    """Audio provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    data: str
    """Base64-encoded audio data."""
    mime_type: Annotated[str, Field(alias="mimeType")]
    type: Literal["audio"]


class BlobResourceContents(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    blob: str
    """Base64-encoded binary data."""
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    uri: str


class CacheableResult(WireModel):
    """A result carrying a TTL hint for client-side caching."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class CancelledNotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    reason: str | None = None
    request_id: Annotated[RequestId | None, Field(alias="requestId")] = None
    """ID of a request previously issued in the same direction."""


ClientResult: TypeAlias = Result


class CompleteResult(WireModel):
    """Server's result for a `completion/complete` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    completion: Completion
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""


class CompleteResultResponse(WireModel):
    """Successful response to a `completion/complete` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: CompleteResult


class EmbeddedResource(WireModel):
    """Resource contents embedded in a prompt or tool-call result."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class ImageContent(WireModel):
    """An image provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    data: str
    """Base64-encoded image data."""
    mime_type: Annotated[str, Field(alias="mimeType")]
    type: Literal["image"]


class JSONRPCErrorResponse(WireModel):
    """An error response to a request."""

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


class ListRootsResult(WireModel):
    """Client's result for a `roots/list` request."""

    roots: list[Root]


class LoggingMessageNotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    data: Any
    """Any JSON-serializable log payload."""
    level: LoggingLevel
    logger: str | None = None


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


class ProgressNotificationParams(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    message: str | None = None
    progress: float
    """Monotonically increasing progress value; `total` may be unknown."""
    progress_token: Annotated[ProgressToken, Field(alias="progressToken")]
    """Token from the originating request, associating this notification with it."""
    total: float | None = None


class Prompt(WireModel):
    """A prompt or prompt template the server offers."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    arguments: list[PromptArgument] | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    name: str
    title: str | None = None


class ReadResourceResult(WireModel):
    """Server's result for a `resources/read` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    contents: list[TextResourceContents | BlobResourceContents]
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class Resource(WireModel):
    """A known resource the server is capable of reading."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    name: str
    size: int | None = None
    """Raw content size in bytes (before base64), if known."""
    title: str | None = None
    uri: str


class ResourceLink(WireModel):
    """A resource reference in a prompt or tool-call result; not guaranteed to appear in `resources/list`."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    name: str
    size: int | None = None
    """Raw content size in bytes (before base64), if known."""
    title: str | None = None
    type: Literal["resource_link"]
    uri: str


class ResourceTemplate(WireModel):
    """A template description for resources available on the server."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """MIME type for all matching resources; include only if uniform across matches."""
    name: str
    title: str | None = None
    uri_template: Annotated[str, Field(alias="uriTemplate")]
    """RFC 6570 URI template."""


class ResourceUpdatedNotification(WireModel):
    """Server-to-client: a resource the client subscribed to via `subscriptions/listen` has changed."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


SingleSelectEnumSchema: TypeAlias = UntitledSingleSelectEnumSchema | TitledSingleSelectEnumSchema


class SubscriptionsAcknowledgedNotification(WireModel):
    """First message on a `subscriptions/listen` stream, reporting which notifications the server honors."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/subscriptions/acknowledged"]
    params: SubscriptionsAcknowledgedNotificationParams


class TextContent(WireModel):
    """Text provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    text: str
    type: Literal["text"]


class Tool(WireModel):
    """Definition for a tool the client can call."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: ToolAnnotations | None = None
    """Display-name precedence: `title`, `annotations.title`, then `name`."""
    description: str | None = None
    icons: list[Icon] | None = None
    input_schema: Annotated[InputSchema, Field(alias="inputSchema")]
    name: str
    output_schema: Annotated[OutputSchema | None, Field(alias="outputSchema")] = None
    title: str | None = None


class CancelledNotification(WireModel):
    """Either side cancelling a previously-issued request; the result will be unused."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


ContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource


class RequestedSchema(WireModel):
    """Restricted JSON Schema subset: top-level properties only, no nesting."""

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class ElicitRequestFormParams(WireModel):
    """Parameters for a form-mode `elicitation/create` request."""

    message: str
    mode: Literal["form"] = "form"
    requested_schema: Annotated[RequestedSchema, Field(alias="requestedSchema")]


ElicitRequestParams: TypeAlias = ElicitRequestFormParams | ElicitRequestURLParams


JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse


JSONRPCResponse: TypeAlias = JSONRPCResultResponse | JSONRPCErrorResponse


class ListPromptsResult(WireModel):
    """Server's result for a `prompts/list` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination position; if present, more results may be available."""
    prompts: list[Prompt]
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class ListPromptsResultResponse(WireModel):
    """Successful response to a `prompts/list` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListPromptsResult


class ListResourceTemplatesResult(WireModel):
    """Server's result for a `resources/templates/list` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination position; if present, more results may be available."""
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class ListResourceTemplatesResultResponse(WireModel):
    """Successful response to a `resources/templates/list` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListResourceTemplatesResult


class ListResourcesResult(WireModel):
    """Server's result for a `resources/list` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination position; if present, more results may be available."""
    resources: list[Resource]
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class ListResourcesResultResponse(WireModel):
    """Successful response to a `resources/list` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListResourcesResult


class ListToolsResult(WireModel):
    """Server's result for a `tools/list` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """Opaque pagination position; if present, more results may be available."""
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    tools: list[Tool]
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class ListToolsResultResponse(WireModel):
    """Successful response to a `tools/list` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListToolsResult


class LoggingMessageNotification(WireModel):
    """Server-to-client log message; opted in via `io.modelcontextprotocol/logLevel` in request `_meta`."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


class ProgressNotification(WireModel):
    """Out-of-band progress update for a long-running request."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class PromptMessage(WireModel):
    """A message returned as part of a prompt; like `SamplingMessage` but supports embedded resources."""

    content: ContentBlock
    role: Role


ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | SubscriptionsAcknowledgedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | LoggingMessageNotification
    | ElicitationCompleteNotification
)


class ToolResultContent(WireModel):
    """The result of a tool use, provided by the user back to the assistant."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    content: list[ContentBlock]
    """Unstructured result; same shape as `CallToolResult.content`."""
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """Default false."""
    structured_content: Annotated[Any | None, Field(alias="structuredContent")] = None
    """Any JSON value; should conform to the tool's `outputSchema` if defined."""
    tool_use_id: Annotated[str, Field(alias="toolUseId")]
    """ID of the corresponding `ToolUseContent`."""
    type: Literal["tool_result"]


class CallToolResult(WireModel):
    """Server's result for a `tools/call` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    content: list[ContentBlock]
    """Unstructured result of the tool call."""
    is_error: Annotated[bool | None, Field(alias="isError")] = None
    """Default false; tool-level errors go here, not as protocol-level errors, so the LLM can see them."""
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    structured_content: Annotated[Any | None, Field(alias="structuredContent")] = None
    """Any JSON value conforming to the tool's `outputSchema` if defined."""


ClientNotification: TypeAlias = CancelledNotification | ProgressNotification


class ElicitRequest(WireModel):
    """Server request to elicit additional information from the user via the client."""

    method: Literal["elicitation/create"]
    params: ElicitRequestParams


class GetPromptResult(WireModel):
    """Server's result for a `prompts/get` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    description: str | None = None
    messages: list[PromptMessage]
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""


SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent


class CreateMessageResult(WireModel):
    """Client's result for a `sampling/createMessage` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    model: str
    """Name of the model that generated the message."""
    role: Role
    stop_reason: Annotated[str | None, Field(alias="stopReason")] = None
    """Open string; standard values are `"endTurn"`, `"stopSequence"`, `"maxTokens"`, `"toolUse"`."""


InputResponse: TypeAlias = CreateMessageResult | ListRootsResult | ElicitResult


InputResponses: TypeAlias = dict[str, InputResponse]
"""Client responses to server-initiated requests, keyed by the matching `InputRequests` key."""


class SamplingMessage(WireModel):
    """A message issued to or received from an LLM API."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    content: (
        TextContent
        | ImageContent
        | AudioContent
        | ToolUseContent
        | ToolResultContent
        | list[SamplingMessageContentBlock]
    )
    role: Role


class CallToolRequest(WireModel):
    """Client request to invoke a tool provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/call"]
    params: CallToolRequestParams


class CallToolRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    arguments: dict[str, Any] | None = None
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    name: str
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class CallToolResultResponse(WireModel):
    """Successful response to a `tools/call` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | CallToolResult


class Elicitation(WireModel):
    """Present if the client supports elicitation from the server."""

    form: JSONObject | None = None
    url: JSONObject | None = None


class Sampling(WireModel):
    """Present if the client supports sampling from an LLM."""

    context: JSONObject | None = None
    """Declares support for context inclusion via `includeContext`."""
    tools: JSONObject | None = None
    """Declares support for `tools` and `toolChoice`."""


class ClientCapabilities(WireModel):
    """Capabilities a client may support; not a closed set."""

    elicitation: Elicitation | None = None
    experimental: dict[str, JSONObject] | None = None
    extensions: dict[str, JSONObject] | None = None
    """Supported MCP extensions, keyed by extension identifier."""
    roots: dict[str, Any] | None = None
    sampling: Sampling | None = None


class CompleteRequest(WireModel):
    """Client request for completion options."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["completion/complete"]
    params: CompleteRequestParams


class CompleteRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    argument: Argument
    context: Context | None = None
    ref: PromptReference | ResourceTemplateReference


class CreateMessageRequest(WireModel):
    """Server request for the client to sample an LLM (with human-in-the-loop approval)."""

    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


class CreateMessageRequestParams(WireModel):
    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """Default `"none"`; `"thisServer"`/`"allServers"` are deprecated (SEP-2596)."""
    max_tokens: Annotated[int, Field(alias="maxTokens")]
    """Requested cap; the client may sample fewer."""
    messages: list[SamplingMessage]
    metadata: JSONObject | None = None
    """Provider-specific passthrough metadata."""
    model_preferences: Annotated[ModelPreferences | None, Field(alias="modelPreferences")] = None
    stop_sequences: Annotated[list[str] | None, Field(alias="stopSequences")] = None
    system_prompt: Annotated[str | None, Field(alias="systemPrompt")] = None
    temperature: float | None = None
    tool_choice: Annotated[ToolChoice | None, Field(alias="toolChoice")] = None
    """Error if set without `ClientCapabilities.sampling.tools`; default `{mode: "auto"}`."""
    tools: list[Tool] | None = None
    """Error if set without `ClientCapabilities.sampling.tools`."""


class DiscoverRequest(WireModel):
    """Client request for the server's supported versions, capabilities, and metadata; servers must implement."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["server/discover"]
    params: RequestParams


class DiscoverResult(WireModel):
    """Server's result for a `server/discover` request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """`"public"` = shareable across users/intermediaries; `"private"` = requesting user only."""
    capabilities: ServerCapabilities
    instructions: str | None = None
    """Natural-language guidance for the LLM; should not duplicate tool descriptions."""
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""
    server_info: Annotated[Implementation, Field(alias="serverInfo")]
    supported_versions: Annotated[list[str], Field(alias="supportedVersions")]
    """Protocol versions this server supports."""
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """Cache freshness hint in ms (HTTP max-age semantics; 0 = immediately stale)."""


class DiscoverResultResponse(WireModel):
    """Successful response to a `server/discover` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: DiscoverResult


class GetPromptRequest(WireModel):
    """Client request for a prompt provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class GetPromptRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    arguments: dict[str, str] | None = None
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    name: str
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class GetPromptResultResponse(WireModel):
    """Successful response to a `prompts/get` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | GetPromptResult


class InputRequiredResult(WireModel):
    """Server signals that more input is needed; at least one of `inputRequests` or `requestState` must be present."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    input_requests: Annotated[InputRequests | None, Field(alias="inputRequests")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None
    result_type: Annotated[str, Field(alias="resultType")]
    """Result-type discriminator; treat absence (pre-2026-07-28 peer) as `"complete"`."""


class InputResponseRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class ListPromptsRequest(WireModel):
    """Client request for the server's prompts and prompt templates."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/list"]
    params: PaginatedRequestParams


class ListResourceTemplatesRequest(WireModel):
    """Client request for the server's resource templates."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/templates/list"]
    params: PaginatedRequestParams


class ListResourcesRequest(WireModel):
    """Client request for the server's resources."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/list"]
    params: PaginatedRequestParams


class ListRootsRequest(WireModel):
    """Server request for the client's root URIs."""

    method: Literal["roots/list"]
    params: RequestParams | None = None


class ListToolsRequest(WireModel):
    """Client request for the server's tools."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/list"]
    params: PaginatedRequestParams


class Data(WireModel):
    required_capabilities: Annotated[ClientCapabilities, Field(alias="requiredCapabilities")]
    """Capabilities the server requires from the client to process the request."""


class Error1(WireModel):
    code: Literal[-32003]
    data: Data
    message: str


class MissingRequiredClientCapabilityError(WireModel):
    """The request requires a client capability not declared in `clientCapabilities` (HTTP: `400 Bad Request`)."""

    error: Error1
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class PaginatedRequest(WireModel):
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: PaginatedRequestParams


class PaginatedRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    cursor: str | None = None
    """Opaque pagination position; results start after this cursor."""


class ReadResourceRequest(WireModel):
    """Client request to read a specific resource URI."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class ReadResourceRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None
    uri: str
    """Any URI scheme; interpretation is server-defined."""


class ReadResourceResultResponse(WireModel):
    """Successful response to a `resources/read` request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | ReadResourceResult


class RequestMetaObject(OpenWireModel):
    """Extends `MetaObject` with request-specific reserved keys; same key naming rules apply."""

    io_modelcontextprotocol_client_capabilities: Annotated[
        ClientCapabilities, Field(alias="io.modelcontextprotocol/clientCapabilities")
    ]
    """Per-request client capabilities; servers must not infer from prior requests."""
    io_modelcontextprotocol_client_info: Annotated[Implementation, Field(alias="io.modelcontextprotocol/clientInfo")]
    """Identifies the client software making the request."""
    io_modelcontextprotocol_log_level: Annotated[
        LoggingLevel | None, Field(alias="io.modelcontextprotocol/logLevel")
    ] = None
    """Log level for this request; absent means no `notifications/message` may be sent."""
    io_modelcontextprotocol_protocol_version: Annotated[str, Field(alias="io.modelcontextprotocol/protocolVersion")]
    """Protocol version for this request; over HTTP, must match the `MCP-Protocol-Version` header."""
    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """Opaque token opting in to `notifications/progress` for this request."""


class RequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]


class ResourceRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    uri: str
    """Any URI scheme; interpretation is server-defined."""


class ServerCapabilities(WireModel):
    """Capabilities a server may support; not a closed set."""

    completions: JSONObject | None = None
    experimental: dict[str, JSONObject] | None = None
    extensions: dict[str, JSONObject] | None = None
    """Supported MCP extensions, keyed by extension identifier."""
    logging: JSONObject | None = None
    prompts: Prompts | None = None
    resources: Resources | None = None
    tools: Tools | None = None


class SubscriptionsListenRequest(WireModel):
    """Client request to open a long-lived channel for receiving notifications outside any specific request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["subscriptions/listen"]
    params: SubscriptionsListenRequestParams


class SubscriptionsListenRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    notifications: SubscriptionFilter
    """Notification types the client opts in to on this stream."""


AnyCallToolResult: TypeAlias = CallToolResult | InputRequiredResult
"""Named alias for `CallToolResultResponse.result` so the wire-method maps can reference it as a value."""

AnyGetPromptResult: TypeAlias = GetPromptResult | InputRequiredResult
"""Everything a `prompts/get` response's `result` may be at this version."""

AnyReadResourceResult: TypeAlias = ReadResourceResult | InputRequiredResult
"""Everything a `resources/read` response's `result` may be at this version."""


ServerResult: TypeAlias = (
    Result
    | InputRequiredResult
    | DiscoverResult
    | ListResourcesResult
    | ListResourceTemplatesResult
    | ReadResourceResult
    | ListPromptsResult
    | GetPromptResult
    | ListToolsResult
    | CallToolResult
    | CompleteResult
)


InputRequest: TypeAlias = CreateMessageRequest | ListRootsRequest | ElicitRequest


ClientRequest: TypeAlias = (
    DiscoverRequest
    | ListResourcesRequest
    | ListResourceTemplatesRequest
    | ReadResourceRequest
    | SubscriptionsListenRequest
    | ListPromptsRequest
    | GetPromptRequest
    | ListToolsRequest
    | CallToolRequest
    | CompleteRequest
)


InputRequests: TypeAlias = dict[str, InputRequest]
"""Server-initiated requests the client must fulfill, keyed by server-assigned identifier."""


JSONArray: TypeAlias = list["JSONValue"]


CallToolRequest.model_rebuild()
CallToolRequestParams.model_rebuild()
CallToolResultResponse.model_rebuild()
Elicitation.model_rebuild()
Sampling.model_rebuild()
ClientCapabilities.model_rebuild()
CompleteRequest.model_rebuild()
CompleteRequestParams.model_rebuild()
CreateMessageRequest.model_rebuild()
CreateMessageRequestParams.model_rebuild()
DiscoverRequest.model_rebuild()
DiscoverResult.model_rebuild()
GetPromptRequest.model_rebuild()
GetPromptRequestParams.model_rebuild()
GetPromptResultResponse.model_rebuild()
InputRequiredResult.model_rebuild()
InputResponseRequestParams.model_rebuild()
ListPromptsRequest.model_rebuild()
ListResourceTemplatesRequest.model_rebuild()
ListResourcesRequest.model_rebuild()
ListRootsRequest.model_rebuild()
ListToolsRequest.model_rebuild()
PaginatedRequest.model_rebuild()
PaginatedRequestParams.model_rebuild()
ReadResourceRequest.model_rebuild()
ReadResourceRequestParams.model_rebuild()
ServerCapabilities.model_rebuild()
SubscriptionsListenRequest.model_rebuild()
