"""Wire-shape models for MCP protocol version 2026-07-28 — not user-facing API.

Defines only what this revision added or changed relative to 2025-11-25;
everything else is imported from the version module that last defined it, so
every import line names the module where a model is defined.
``REMOVED_FROM_PREVIOUS_VERSION`` lists the names 2025-11-25 defined that
this revision dropped.

Consumed by ``mcp.types.wire``: ``serialize_for`` re-validates each outbound
monolith dump through the negotiated version's models, importing the version
module lazily on first boundary use (never at ``import mcp.types``).

Initially generated from the pinned 2026-07-28 schema (spec commit
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
from typing_extensions import TypeAliasType

from mcp.types._wire_base import OpenWireModel, WireModel

# Unchanged since 2024-11-05:
from mcp.types.v2024_11_05 import (
    Argument,
    Cursor,
    Error,
    LoggingLevel,
    ModelHint,
    ModelPreferences,
    ProgressToken,
    Prompts,
    RequestId,
    Resources,
    Role,
)

# Unchanged since 2025-03-26:
from mcp.types.v2025_03_26 import (
    ToolAnnotations,
)

# Unchanged since 2025-06-18:
from mcp.types.v2025_06_18 import (
    Annotations,
    BaseMetadata,
    BooleanSchema,
    Context,
    PromptArgument,
    PromptReference,
    ResourceTemplateReference,
)

# Unchanged since 2025-11-25:
from mcp.types.v2025_11_25 import (
    ElicitationCompleteNotification,
    EnumSchema,
    Icon,
    Icons,
    Implementation,
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    LegacyTitledEnumSchema,
    MultiSelectEnumSchema,
    Notification,
    Request,
    SingleSelectEnumSchema,
    StringSchema,
    TitledMultiSelectEnumSchema,
    TitledSingleSelectEnumSchema,
    ToolChoice,
    UntitledMultiSelectEnumSchema,
    UntitledSingleSelectEnumSchema,
)

REMOVED_FROM_PREVIOUS_VERSION: Final[frozenset[str]] = frozenset(
    {
        "CancelTaskRequest",
        "CancelTaskResult",
        "CreateTaskResult",
        "GetTaskPayloadRequest",
        "GetTaskPayloadResult",
        "GetTaskRequest",
        "GetTaskResult",
        "InitializeRequest",
        "InitializeRequestParams",
        "InitializeResult",
        "InitializedNotification",
        "ListTasksRequest",
        "ListTasksResult",
        "PingRequest",
        "RelatedTaskMetadata",
        "RootsListChangedNotification",
        "ServerRequest",
        "SetLevelRequest",
        "SetLevelRequestParams",
        "SubscribeRequest",
        "SubscribeRequestParams",
        "Task",
        "TaskAugmentedRequestParams",
        "TaskMetadata",
        "TaskStatus",
        "TaskStatusNotification",
        "TaskStatusNotificationParams",
        "ToolExecution",
        "URLElicitationRequiredError",
        "UnsubscribeRequest",
        "UnsubscribeRequestParams",
    }
)

__all__ = [
    "Annotations",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "BooleanSchema",
    "CacheableResult",
    "CallToolRequest",
    "CallToolRequestParams",
    "CallToolResult",
    "CallToolResultResponse",
    "CancelledNotification",
    "CancelledNotificationParams",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteRequestParams",
    "CompleteResult",
    "CompleteResultResponse",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageRequestParams",
    "CreateMessageResult",
    "Cursor",
    "DiscoverRequest",
    "DiscoverResult",
    "DiscoverResultResponse",
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
    "GetPromptResultResponse",
    "Icon",
    "Icons",
    "ImageContent",
    "Implementation",
    "InputRequest",
    "InputRequests",
    "InputRequiredResult",
    "InputResponse",
    "InputResponseRequestParams",
    "InputResponses",
    "InternalError",
    "InvalidParamsError",
    "InvalidRequestError",
    "JSONArray",
    "JSONObject",
    "JSONRPCErrorResponse",
    "JSONRPCMessage",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCResultResponse",
    "JSONValue",
    "LegacyTitledEnumSchema",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListPromptsResultResponse",
    "ListResourceTemplatesRequest",
    "ListResourceTemplatesResult",
    "ListResourceTemplatesResultResponse",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListResourcesResultResponse",
    "ListRootsRequest",
    "ListRootsResult",
    "ListToolsRequest",
    "ListToolsResult",
    "ListToolsResultResponse",
    "LoggingLevel",
    "LoggingMessageNotification",
    "LoggingMessageNotificationParams",
    "MetaObject",
    "MethodNotFoundError",
    "MissingRequiredClientCapabilityError",
    "ModelHint",
    "ModelPreferences",
    "MultiSelectEnumSchema",
    "Notification",
    "NotificationParams",
    "NumberSchema",
    "PaginatedRequest",
    "PaginatedRequestParams",
    "PaginatedResult",
    "ParseError",
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
    "ReadResourceResultResponse",
    "Request",
    "RequestId",
    "RequestMetaObject",
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
    "ResultType",
    "Role",
    "Root",
    "SamplingMessage",
    "SamplingMessageContentBlock",
    "ServerCapabilities",
    "ServerNotification",
    "ServerResult",
    "SingleSelectEnumSchema",
    "StringSchema",
    "SubscriptionFilter",
    "SubscriptionsAcknowledgedNotification",
    "SubscriptionsAcknowledgedNotificationParams",
    "SubscriptionsListenRequest",
    "SubscriptionsListenRequestParams",
    "TextContent",
    "TextResourceContents",
    "TitledMultiSelectEnumSchema",
    "TitledSingleSelectEnumSchema",
    "Tool",
    "ToolAnnotations",
    "ToolChoice",
    "ToolListChangedNotification",
    "ToolResultContent",
    "ToolUseContent",
    "UnsupportedProtocolVersionError",
    "UntitledMultiSelectEnumSchema",
    "UntitledSingleSelectEnumSchema",
]

# --- Recursive aliases new or changed in 2026-07-28 ---
# (defined first: their values are strings resolved only when a model is
# built, and static type checkers need the definition before its uses)

# Deliberate deviation from the pinned schema.json, which renders JSONValue's
# primitive branch as ["string", "integer", "boolean"] — its schema.ts source
# defines all six JSON types (string | number | boolean | null | object |
# array), so the render is missing fractional numbers and null. This alias
# follows the schema.ts definition: capability values like {"ratio": 0.5} or
# nested nulls must survive revalidation. The generated oracle keeps the
# schema.json shape verbatim; the surface test pins this alias separately.
JSONValue = TypeAliasType("JSONValue", "JSONObject | list[JSONValue] | str | int | float | bool | None")

JSONObject = TypeAliasType("JSONObject", dict[str, "JSONValue"])

# --- New in 2026-07-28 ---


class InternalError(WireModel):
    """A JSON-RPC error indicating that an internal error occurred on the receiver. This error is returned when the
    receiver encounters an unexpected condition that prevents it from fulfilling the request.
    """

    code: Literal[-32603]
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


class InvalidParamsError(WireModel):
    """A JSON-RPC error indicating that the method parameters are invalid or malformed.

    In MCP, this error is returned in various contexts when request parameters fail validation:

    - **Tools**: Unknown tool name or invalid tool arguments
    - **Prompts**: Unknown prompt name or missing required arguments
    - **Pagination**: Invalid or expired cursor values
    - **Logging**: Invalid log level
    - **Elicitation**: Server requests an elicitation mode not declared in client capabilities
    - **Sampling**: Missing tool result or tool results mixed with other content
    """

    code: Literal[-32602]
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


class InvalidRequestError(WireModel):
    """A JSON-RPC error indicating that the request is not a valid request object. This error is returned when the
    message structure does not conform to the JSON-RPC 2.0 specification requirements for a request (e.g., missing
    required fields like `jsonrpc` or `method`, or using invalid types for these fields).
    """

    code: Literal[-32600]
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


class MetaObject(OpenWireModel):
    """Represents the contents of a `_meta` field, which clients and servers use to attach additional metadata to their
    interactions.

    Certain key names are reserved by MCP for protocol-level metadata; implementations MUST NOT make assumptions about
    values at these keys. Additionally, specific schema definitions may reserve particular names for purpose-specific
    metadata, as declared in those definitions.

    Valid keys have two segments:

    **Prefix:**
    - Optional — if specified, MUST be a series of _labels_ separated by dots (`.`), followed by a slash (`/`).
    - Labels MUST start with a letter and end with a letter or digit. Interior characters may be letters, digits, or
    hyphens (`-`).
    - Implementations SHOULD use reverse DNS notation (e.g., `com.example/` rather than `example.com/`).
    - Any prefix where the second label is `modelcontextprotocol` or `mcp` is **reserved** for MCP use. For example:
    `io.modelcontextprotocol/`, `dev.mcp/`, `org.modelcontextprotocol.api/`, and `com.mcp.tools/` are all reserved.
    However, `com.example.mcp/` is NOT reserved, as the second label is `example`.

    **Name:**
    - Unless empty, MUST start and end with an alphanumeric character (`[a-z0-9A-Z]`).
    - Interior characters may be alphanumeric, hyphens (`-`), underscores (`_`), or dots (`.`).
    """


class MethodNotFoundError(WireModel):
    """A JSON-RPC error indicating that the requested method does not exist or is not available.

    In MCP, a server returns this error when a client invokes a method the server does not implement — either a
    genuinely unknown method, or one gated behind a server capability the server did not advertise (e.g., calling
    `prompts/list` when the `prompts` capability was not advertised).

    A request that requires a client capability the client did not declare is signalled instead by
    MissingRequiredClientCapabilityError (`-32003`).
    """

    code: Literal[-32601]
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


class ParseError(WireModel):
    """A JSON-RPC error indicating that invalid JSON was received by the server. This error is returned when the
    server cannot parse the JSON text of a message.
    """

    code: Literal[-32700]
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


class SubscriptionFilter(WireModel):
    """The set of notification types a client may opt in to on a
    SubscriptionsListenRequestsubscriptions/listen request.

    Each notification type is **opt-in**; the server **MUST NOT** send
    notification types the client has not explicitly requested here.
    """

    # Stays open: filter contents are extensible on the wire.
    model_config = ConfigDict(
        extra="allow",
    )
    prompts_list_changed: Annotated[bool | None, Field(alias="promptsListChanged")] = None
    """
    If true, receive PromptListChangedNotificationnotifications/prompts/list_changed.
    """
    resource_subscriptions: Annotated[list[str] | None, Field(alias="resourceSubscriptions")] = None
    """
    Subscribe to ResourceUpdatedNotificationnotifications/resources/updated for these resource URIs.
    Replaces the former `resources/subscribe` RPC.
    """
    resources_list_changed: Annotated[bool | None, Field(alias="resourcesListChanged")] = None
    """
    If true, receive ResourceListChangedNotificationnotifications/resources/list_changed.
    """
    tools_list_changed: Annotated[bool | None, Field(alias="toolsListChanged")] = None
    """
    If true, receive ToolListChangedNotificationnotifications/tools/list_changed.
    """


class SubscriptionsAcknowledgedNotificationParams(WireModel):
    """Parameters for a SubscriptionsAcknowledgedNotificationnotifications/subscriptions/acknowledged notification."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    notifications: SubscriptionFilter
    """
    The subset of requested notification types the server agreed to honor.
    Only includes notification types the server actually supports; if the
    client requested an unsupported type (e.g., `promptsListChanged` when
    the server has no prompts), it is omitted from this set.
    """


class Data1(WireModel):
    """Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """

    requested: str
    """
    The protocol version that was requested by the client.
    """
    supported: list[str]
    """
    Protocol versions the server supports. The client should choose a
    mutually supported version from this list and retry.
    """


class Error2(WireModel):
    code: Literal[-32004]
    """
    The error type that occurred.
    """
    data: Data1
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """
    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single sentence.
    """


class UnsupportedProtocolVersionError(WireModel):
    """Returned when the request's protocol version is unknown to the server or
    unsupported (e.g., a known experimental or draft version the server has
    chosen not to implement). For HTTP, the response status code MUST be
    `400 Bad Request`.
    """

    error: Error2
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class CacheableResult(WireModel):
    """A result that supports a time-to-live (TTL) hint for client-side caching."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class CompleteResultResponse(WireModel):
    """A successful response from the server for a CompleteRequestcompletion/complete request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: CompleteResult


class SubscriptionsAcknowledgedNotification(WireModel):
    """Sent by the server as the first message on a
    SubscriptionsListenRequestsubscriptions/listen stream to acknowledge
    that the subscription has been established and to report which notification
    types it agreed to honor.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/subscriptions/acknowledged"]
    params: SubscriptionsAcknowledgedNotificationParams


class ListPromptsResultResponse(WireModel):
    """A successful response from the server for a ListPromptsRequestprompts/list request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListPromptsResult


class ListResourceTemplatesResultResponse(WireModel):
    """A successful response from the server for a ListResourceTemplatesRequestresources/templates/list request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListResourceTemplatesResult


class ListResourcesResultResponse(WireModel):
    """A successful response from the server for a ListResourcesRequestresources/list request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListResourcesResult


class ListToolsResultResponse(WireModel):
    """A successful response from the server for a ListToolsRequesttools/list request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: ListToolsResult


class CallToolResultResponse(WireModel):
    """A successful response from the server for a CallToolRequesttools/call request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | CallToolResult


class DiscoverRequest(WireModel):
    """A request from the client asking the server to advertise its supported
    protocol versions, capabilities, and other metadata. Servers **MUST**
    implement `server/discover`. Clients **MAY** call it but are not required
    to — version negotiation can also happen inline via per-request `_meta`.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["server/discover"]
    params: RequestParams


class DiscoverResult(WireModel):
    """The result returned by the server for a DiscoverRequestserver/discover request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    capabilities: ServerCapabilities
    """
    The capabilities of the server.
    """
    instructions: str | None = None
    """
    Natural-language guidance describing the server and its features.

    This can be used by clients to improve an LLM's understanding of
    available tools (e.g., by including it in a system prompt). It should
    focus on information that helps the model use the server effectively
    and should not duplicate information already in tool descriptions.
    """
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    server_info: Annotated[Implementation, Field(alias="serverInfo")]
    """
    Information about the server software implementation.
    """
    supported_versions: Annotated[list[str], Field(alias="supportedVersions")]
    """
    MCP Protocol Versions this server supports. The client should choose a
    version from this list for use in subsequent requests.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class DiscoverResultResponse(WireModel):
    """A successful response from the server for a DiscoverRequestserver/discover request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: DiscoverResult


class GetPromptResultResponse(WireModel):
    """A successful response from the server for a GetPromptRequestprompts/get request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | GetPromptResult


class InputRequiredResult(WireModel):
    """An InputRequiredResult sent by the server to indicate that additional input is needed
    before the request can be completed.

    At least one of `inputRequests` or `requestState` MUST be present.
    """

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    input_requests: Annotated[InputRequests | None, Field(alias="inputRequests")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """


class InputResponseRequestParams(WireModel):
    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class MissingRequiredClientCapabilityError(WireModel):
    """Returned when processing a request requires a capability the client did not
    declare in `clientCapabilities`. For HTTP, the response status code MUST be
    `400 Bad Request`.
    """

    error: Error1
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class ReadResourceResultResponse(WireModel):
    """A successful response from the server for a ReadResourceRequestresources/read request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: InputRequiredResult | ReadResourceResult


class RequestMetaObject(OpenWireModel):
    """Extends MetaObject with additional request-specific fields. All key naming rules from `MetaObject` apply."""

    io_modelcontextprotocol_client_capabilities: Annotated[
        ClientCapabilities, Field(alias="io.modelcontextprotocol/clientCapabilities")
    ]
    """
    The client's capabilities for this specific request. Required.

    Capabilities are declared per-request rather than once at initialization;
    an empty object means the client supports no optional capabilities.
    Servers MUST NOT infer capabilities from prior requests.
    """
    io_modelcontextprotocol_client_info: Annotated[Implementation, Field(alias="io.modelcontextprotocol/clientInfo")]
    """
    Identifies the client software making the request. Required.

    The Implementation schema requires `name` and `version`; other
    fields are optional.
    """
    io_modelcontextprotocol_log_level: Annotated[
        LoggingLevel | None, Field(alias="io.modelcontextprotocol/logLevel")
    ] = None
    """
    The desired log level for this request. Optional.

    If absent, the server MUST NOT send any LoggingMessageNotificationnotifications/message
    notifications for this request. The client opts in to log messages by
    explicitly setting a level. Replaces the former `logging/setLevel` RPC.
    """
    io_modelcontextprotocol_protocol_version: Annotated[str, Field(alias="io.modelcontextprotocol/protocolVersion")]
    """
    The MCP Protocol Version being used for this request. Required.

    For the HTTP transport, this value MUST match the `MCP-Protocol-Version`
    header; otherwise the server MUST return a `400 Bad Request`. If the
    server does not support the requested version, it MUST return an
    UnsupportedProtocolVersionError.
    """
    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """
    If specified, the caller is requesting out-of-band progress notifications for this request (as represented by
    ProgressNotificationnotifications/progress). The value of this parameter is an opaque token that will be attached to
    any subsequent notifications. The receiver is not obligated to provide these notifications.
    """


class SubscriptionsListenRequest(WireModel):
    """Sent from the client to open a long-lived channel for receiving notifications
    outside the context of a specific request. Replaces the previous HTTP GET
    endpoint and ensures consistent behavior between HTTP and STDIO.
    """

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["subscriptions/listen"]
    params: SubscriptionsListenRequestParams


class SubscriptionsListenRequestParams(WireModel):
    """Parameters for a SubscriptionsListenRequestsubscriptions/listen request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    notifications: SubscriptionFilter
    """
    The notifications the client opts in to on this stream. The server
    **MUST NOT** send notification types the client has not explicitly
    requested.
    """


# --- Changed in 2026-07-28 ---


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
    values: Annotated[list[str], Field(max_length=100)]
    """
    An array of completion values. Must not exceed 100 items.
    """


class ElicitRequestURLParams(WireModel):
    """The parameters for a request to elicit information from the user via a URL in the client."""

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
    url: str
    """
    The URL that the user should navigate to.
    """


class ElicitResult(WireModel):
    """The result returned by the client for an ElicitRequestelicitation/create request."""

    action: Literal["accept", "cancel", "decline"]
    """
    The user action in response to the elicitation.
    - `"accept"`: User submitted the form/confirmed the action
    - `"decline"`: User explicitly declined the action
    - `"cancel"`: User dismissed without making an explicit choice
    """
    # Deliberate deviation from the pinned schema.json, which renders the
    # value union's number arm as "integer" — its schema.ts source types form
    # answers string | number | boolean | string[], so fractional answers are
    # legal wire values (the same render artifact fixed for JSONValue above).
    # The float arm follows schema.ts; the generated oracle keeps the
    # rendering verbatim and the surface test pins this annotation separately.
    content: dict[str, list[str] | str | int | float | bool] | None = None
    """
    The submitted form data, only present when action is `"accept"` and mode was `"form"`.
    Contains values matching the requested schema.
    Omitted for out-of-band mode responses.
    """


class NotificationParams(WireModel):
    """Common params for any notification."""

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
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """


class PromptListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of prompts it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class ResourceContents(WireModel):
    """The contents of a specific resource or sub-resource."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: str
    """
    The URI of this resource.
    """


class ResourceListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of resources it can read
    from has changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class ResourceUpdatedNotificationParams(WireModel):
    """Parameters for a `notifications/resources/updated` notification."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    uri: str
    """
    The URI of the resource that has been updated. This might be a sub-resource of the one that the client actually
    subscribed to.
    """


class Result(WireModel):
    """Common result fields."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """


class Root(WireModel):
    """Represents a root directory or file that the server can operate on."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    name: str | None = None
    """
    An optional name for the root. This can be used to provide a human-readable
    identifier for the root, which may be useful for display purposes or for
    referencing the root in other parts of the application.
    """
    uri: str
    """
    The URI identifying the root. This *must* start with `file://` for now.
    This restriction may be relaxed in future versions of the protocol to allow
    other URI schemes.
    """


class Tools(WireModel):
    """Present if the server offers any tools to call."""

    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the tool list.
    """


class TextResourceContents(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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
    """A JSON Schema object defining the expected parameters for the tool.

    Tool arguments are always JSON objects, so `type: "object"` is required at the root.
    Beyond that, any JSON Schema 2020-12 keyword may appear alongside `type` — including
    composition keywords (`oneOf`, `anyOf`, `allOf`, `not`), conditional keywords
    (`if`/`then`/`else`), reference keywords (`$ref`, `$defs`, `$anchor`), and any other
    standard validation or annotation keywords.

    Defaults to JSON Schema 2020-12 when no explicit `$schema` is provided.
    """

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    type: Literal["object"]


class OutputSchema(WireModel):
    """An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult. This can be any valid JSON Schema 2020-12.

    Defaults to JSON Schema 2020-12 when no explicit `$schema` is provided.
    """

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None


class ToolListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of tools it offers has
    changed. This may be issued by servers without any previous subscription from the client.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


class ToolUseContent(WireModel):
    """A request from the assistant to call a tool."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    """
    Optional metadata about the tool use. Clients SHOULD preserve this field when
    including tool uses in subsequent sampling requests to enable caching optimizations.
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


class AudioContent(WireModel):
    """Audio provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class BlobResourceContents(WireModel):
    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class CancelledNotificationParams(WireModel):
    """Parameters for a `notifications/cancelled` notification."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    reason: str | None = None
    """
    An optional string describing the reason for the cancellation. This MAY be logged or presented to the user.
    """
    request_id: Annotated[RequestId | None, Field(alias="requestId")] = None
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    """


class CompleteResult(WireModel):
    """The result returned by the server for a CompleteRequestcompletion/complete request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    completion: Completion
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """


class EmbeddedResource(WireModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"]


class ImageContent(WireModel):
    """An image provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class JSONRPCResultResponse(WireModel):
    """A successful (non-error) response to a request."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class ListRootsResult(WireModel):
    """The result returned by the client for a ListRootsRequestroots/list request.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    roots: list[Root]


class LoggingMessageNotificationParams(WireModel):
    """Parameters for a `notifications/message` notification."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class ProgressNotificationParams(WireModel):
    """Parameters for a ProgressNotificationnotifications/progress notification."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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


class ReadResourceResult(WireModel):
    """The result returned by the server for a ReadResourceRequestresources/read request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    contents: list[TextResourceContents | BlobResourceContents]
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class Resource(WireModel):
    """A known resource that the server is capable of reading."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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

    Note: resource links returned by tools are not guaranteed to appear in the results of
    ListResourcesRequestresources/list requests.
    """

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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
    again. This is only sent for resources the client opted in to via the `resourceSubscriptions` field of a
    SubscriptionsListenRequestsubscriptions/listen request.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class TextContent(WireModel):
    """Text provided to or from an LLM."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    annotations: ToolAnnotations | None = None
    """
    Optional additional tool information.

    Display name precedence order is: `title`, `annotations.title`, then `name`.
    """
    description: str | None = None
    """
    A human-readable description of the tool.

    This can be used by clients to improve the LLM's understanding of available tools. It can be thought of like a
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
    input_schema: Annotated[InputSchema, Field(alias="inputSchema")]
    """
    A JSON Schema object defining the expected parameters for the tool.

    Tool arguments are always JSON objects, so `type: "object"` is required at the root.
    Beyond that, any JSON Schema 2020-12 keyword may appear alongside `type` — including
    composition keywords (`oneOf`, `anyOf`, `allOf`, `not`), conditional keywords
    (`if`/`then`/`else`), reference keywords (`$ref`, `$defs`, `$anchor`), and any other
    standard validation or annotation keywords.

    Defaults to JSON Schema 2020-12 when no explicit `$schema` is provided.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't
    present).
    """
    output_schema: Annotated[OutputSchema | None, Field(alias="outputSchema")] = None
    """
    An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult. This can be any valid JSON Schema 2020-12.

    Defaults to JSON Schema 2020-12 when no explicit `$schema` is provided.
    """
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class CancelledNotification(WireModel):
    """This notification can be sent by either side to indicate that it is cancelling a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it is always possible that this
    notification MAY arrive after the request has already finished.

    This notification indicates that the result will be unused, so any associated processing SHOULD cease.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


class RequestedSchema(WireModel):
    """A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class ElicitRequestFormParams(WireModel):
    """The parameters for a request to elicit non-sensitive information from the user via a form in the client."""

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


class ListPromptsResult(WireModel):
    """The result returned by the server for a ListPromptsRequestprompts/list request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    prompts: list[Prompt]
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class ListResourceTemplatesResult(WireModel):
    """The result returned by the server for a ListResourceTemplatesRequestresources/templates/list request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resource_templates: Annotated[list[ResourceTemplate], Field(alias="resourceTemplates")]
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class ListResourcesResult(WireModel):
    """The result returned by the server for a ListResourcesRequestresources/list request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    resources: list[Resource]
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class ListToolsResult(WireModel):
    """The result returned by the server for a ListToolsRequesttools/list request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    cache_scope: Annotated[Literal["private", "public"], Field(alias="cacheScope")]
    """
    Indicates the intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    - `"public"`: Any client or intermediary (e.g., shared gateway, proxy)
      MAY cache the response and serve it to any user.
    - `"private"`: Only the requesting user's client MAY cache the response.
      Shared caches (e.g., multi-tenant gateways) MUST NOT serve a cached
      copy to a different user.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    tools: list[Tool]
    ttl_ms: Annotated[int, Field(alias="ttlMs", ge=0)]
    """
    A hint from the server indicating how long (in milliseconds) the
    client MAY cache this response before re-fetching. Semantics are
    analogous to HTTP Cache-Control max-age.

    - If 0, The response SHOULD be considered immediately stale,
      The client MAY re-fetch every time the result is needed.
    - If positive, the client SHOULD consider the result fresh for this many
      milliseconds after receiving the response.
    """


class LoggingMessageNotification(WireModel):
    """JSONRPCNotification of a log message passed from server to client. The client opts in by setting
    `"io.modelcontextprotocol/logLevel"` in a request's `_meta`.
    """

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


class ProgressNotification(WireModel):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    jsonrpc: Literal["2.0"]
    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class PromptMessage(WireModel):
    """Describes a message returned as part of a prompt.

    This is similar to SamplingMessage, but also supports the embedding of
    resources from the MCP server.
    """

    content: ContentBlock
    role: Role


class ToolResultContent(WireModel):
    """The result of a tool use, provided by the user back to the assistant."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    """
    Optional metadata about the tool result. Clients SHOULD preserve this field when
    including tool results in subsequent sampling requests to enable caching optimizations.
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
    An optional structured result value.

    This can be any JSON value (object, array, string, number, boolean, or null).
    If the tool defined an Tool.outputSchema, this SHOULD conform to that schema.
    """
    tool_use_id: Annotated[str, Field(alias="toolUseId")]
    """
    The ID of the tool use this result corresponds to.

    This MUST match the ID from a previous ToolUseContent.
    """
    type: Literal["tool_result"]


class CallToolResult(WireModel):
    """The result returned by the server for a CallToolRequesttools/call request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
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
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """
    structured_content: Annotated[Any | None, Field(alias="structuredContent")] = None
    """
    An optional JSON value that represents the structured result of the tool call.

    This can be any JSON value (object, array, string, number, boolean, or null)
    that conforms to the tool's outputSchema if one is defined.
    """


class ElicitRequest(WireModel):
    """A request from the server to elicit additional information from the user via the client."""

    method: Literal["elicitation/create"]
    params: ElicitRequestParams


class GetPromptResult(WireModel):
    """The result returned by the server for a GetPromptRequestprompts/get request."""

    meta: Annotated[MetaObject | None, Field(alias="_meta")] = None
    description: str | None = None
    """
    An optional description for the prompt.
    """
    messages: list[PromptMessage]
    result_type: Annotated[str, Field(alias="resultType")]
    """
    Indicates the type of the result, which allows the client to determine
    how to parse the result object.

    Servers implementing this protocol version MUST include this field.
    For backward compatibility, when a client receives a result from a
    server implementing an earlier protocol version (which does not include
    `resultType`), the client MUST treat the absent field as `"complete"`.
    """


class CreateMessageResult(WireModel):
    """The result returned by the client for a CreateMessageRequestsampling/createMessage request.
    The client should inform the user before returning the sampled message, to allow them
    to inspect the response (human in the loop) and decide whether to allow the server to see it.
    """

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
    """
    The name of the model that generated the message.
    """
    role: Role
    stop_reason: Annotated[str | None, Field(alias="stopReason")] = None
    """
    The reason why sampling stopped, if known.

    Standard values:
    - `"endTurn"`: Natural end of the assistant's turn
    - `"stopSequence"`: A stop sequence was encountered
    - `"maxTokens"`: Maximum token limit was reached
    - `"toolUse"`: The model wants to use one or more tools

    This field is an open string to allow for provider-specific stop reasons.
    """


class SamplingMessage(WireModel):
    """Describes a message issued to or received from an LLM API."""

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
    """Used by the client to invoke a tool provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/call"]
    params: CallToolRequestParams


class CallToolRequestParams(WireModel):
    """Parameters for a `tools/call` request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    arguments: dict[str, Any] | None = None
    """
    Arguments to use for the tool call.
    """
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    name: str
    """
    The name of the tool.
    """
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class Elicitation(WireModel):
    """Present if the client supports elicitation from the server."""

    form: JSONObject | None = None
    url: JSONObject | None = None


class Sampling(WireModel):
    """Present if the client supports sampling from an LLM."""

    context: JSONObject | None = None
    """
    Whether the client supports context inclusion via `includeContext` parameter.
    If not declared, servers SHOULD only use `includeContext: "none"` (or omit it).
    """
    tools: JSONObject | None = None
    """
    Whether the client supports tool use via `tools` and `toolChoice` parameters.
    """


class ClientCapabilities(WireModel):
    """Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any client can define its own, additional capabilities.
    """

    elicitation: Elicitation | None = None
    """
    Present if the client supports elicitation from the server.
    """
    experimental: dict[str, JSONObject] | None = None
    """
    Experimental, non-standard capabilities that the client supports.
    """
    extensions: dict[str, JSONObject] | None = None
    """
    Optional MCP extensions that the client supports. Keys are extension identifiers
    (e.g., "io.modelcontextprotocol/oauth-client-credentials"), and values are
    per-extension settings objects. An empty object indicates support with no settings.
    """
    roots: dict[str, Any] | None = None
    """
    Present if the client supports listing roots.
    """
    sampling: Sampling | None = None
    """
    Present if the client supports sampling from an LLM.
    """


class CompleteRequest(WireModel):
    """A request from the client to the server, to ask for completion options."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["completion/complete"]
    params: CompleteRequestParams


class CompleteRequestParams(WireModel):
    """Parameters for a `completion/complete` request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    argument: Argument
    """
    The argument's information
    """
    context: Context | None = None
    """
    Additional, optional context for completions
    """
    ref: PromptReference | ResourceTemplateReference


class CreateMessageRequest(WireModel):
    """A request from the server to sample an LLM via the client. The client has full discretion over which model to
    select. The client should also inform the user before beginning sampling, to allow them to inspect the request
    (human in the loop) and decide whether to approve it.
    """

    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


class CreateMessageRequestParams(WireModel):
    """Parameters for a `sampling/createMessage` request."""

    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """
    A request to include context from one or more MCP servers (including the caller), to be attached to the prompt.
    The client MAY ignore this request.

    Default is `"none"`. The values `"thisServer"` and `"allServers"` are deprecated (SEP-2596): servers SHOULD
    omit this field or use `"none"`, and SHOULD only use the deprecated values if the client declares
    ClientCapabilities.sampling.context.
    """
    max_tokens: Annotated[int, Field(alias="maxTokens")]
    """
    The requested maximum number of tokens to sample (to prevent runaway completions).

    The client MAY choose to sample fewer tokens than the requested maximum.
    """
    messages: list[SamplingMessage]
    metadata: JSONObject | None = None
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


class GetPromptRequest(WireModel):
    """Used by the client to get a prompt provided by the server."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class GetPromptRequestParams(WireModel):
    """Parameters for a `prompts/get` request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    arguments: dict[str, str] | None = None
    """
    Arguments to use for templating the prompt.
    """
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    name: str
    """
    The name of the prompt or prompt template.
    """
    request_state: Annotated[str | None, Field(alias="requestState")] = None


class ListPromptsRequest(WireModel):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/list"]
    params: PaginatedRequestParams


class ListResourceTemplatesRequest(WireModel):
    """Sent from the client to request a list of resource templates the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/templates/list"]
    params: PaginatedRequestParams


class ListResourcesRequest(WireModel):
    """Sent from the client to request a list of resources the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/list"]
    params: PaginatedRequestParams


class ListRootsRequest(WireModel):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    method: Literal["roots/list"]
    params: RequestParams | None = None


class ListToolsRequest(WireModel):
    """Sent from the client to request a list of tools the server has."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/list"]
    params: PaginatedRequestParams


class Data(WireModel):
    """Additional information about the error. The value of this member is defined by the sender (e.g. detailed error
    information, nested errors etc.).
    """

    required_capabilities: Annotated[ClientCapabilities, Field(alias="requiredCapabilities")]
    """
    The capabilities the server requires from the client to process this request.
    """


class Error1(WireModel):
    code: Literal[-32003]
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


class PaginatedRequest(WireModel):
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: PaginatedRequestParams


class PaginatedRequestParams(WireModel):
    """Common params for paginated requests."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class ReadResourceRequest(WireModel):
    """Sent from the client to the server, to read a specific resource URI."""

    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class ReadResourceRequestParams(WireModel):
    """Parameters for a `resources/read` request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    input_responses: Annotated[InputResponses | None, Field(alias="inputResponses")] = None
    request_state: Annotated[str | None, Field(alias="requestState")] = None
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class RequestParams(WireModel):
    """Common params for any request."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]


class ResourceRequestParams(WireModel):
    """Common params for resource-related requests."""

    meta: Annotated[RequestMetaObject, Field(alias="_meta")]
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class ServerCapabilities(WireModel):
    """Capabilities that a server may support. Known capabilities are defined here, in this schema, but this is not a
    closed set: any server can define its own, additional capabilities.
    """

    completions: JSONObject | None = None
    """
    Present if the server supports argument autocompletion suggestions.
    """
    experimental: dict[str, JSONObject] | None = None
    """
    Experimental, non-standard capabilities that the server supports.
    """
    extensions: dict[str, JSONObject] | None = None
    """
    Optional MCP extensions that the server supports. Keys are extension identifiers
    (e.g., "io.modelcontextprotocol/tasks"), and values are per-extension settings
    objects. An empty object indicates support with no settings.
    """
    logging: JSONObject | None = None
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


# --- Aliases new or changed in 2026-07-28 ---
# (defined last: an alias right-hand side evaluates its referents at import)

ResultType: TypeAlias = str

ClientResult: TypeAlias = Result

EmptyResult: TypeAlias = Result

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

ContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource

ElicitRequestParams: TypeAlias = ElicitRequestFormParams | ElicitRequestURLParams

JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse

JSONRPCResponse: TypeAlias = JSONRPCResultResponse | JSONRPCErrorResponse

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

ClientNotification: TypeAlias = CancelledNotification | ProgressNotification

SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent

InputResponse: TypeAlias = CreateMessageResult | ListRootsResult | ElicitResult

InputResponses: TypeAlias = dict[str, InputResponse]

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

JSONArray: TypeAlias = list["JSONValue"]

CompleteResultResponse.model_rebuild()
ListPromptsResultResponse.model_rebuild()
ListResourceTemplatesResultResponse.model_rebuild()
ListResourcesResultResponse.model_rebuild()
ListToolsResultResponse.model_rebuild()
CallToolResultResponse.model_rebuild()
DiscoverRequest.model_rebuild()
DiscoverResult.model_rebuild()
GetPromptResultResponse.model_rebuild()
InputRequiredResult.model_rebuild()
InputResponseRequestParams.model_rebuild()
MissingRequiredClientCapabilityError.model_rebuild()
ReadResourceResultResponse.model_rebuild()
RequestMetaObject.model_rebuild()
SubscriptionsListenRequest.model_rebuild()
RequestedSchema.model_rebuild()
PromptMessage.model_rebuild()
ToolResultContent.model_rebuild()
CallToolResult.model_rebuild()
ElicitRequest.model_rebuild()
CreateMessageResult.model_rebuild()
SamplingMessage.model_rebuild()
CallToolRequest.model_rebuild()
CallToolRequestParams.model_rebuild()
Elicitation.model_rebuild()
Sampling.model_rebuild()
ClientCapabilities.model_rebuild()
CompleteRequest.model_rebuild()
CompleteRequestParams.model_rebuild()
CreateMessageRequest.model_rebuild()
CreateMessageRequestParams.model_rebuild()
GetPromptRequest.model_rebuild()
GetPromptRequestParams.model_rebuild()
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
