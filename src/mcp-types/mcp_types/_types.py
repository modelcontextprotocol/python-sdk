"""Version-superset MCP protocol models.

One model per protocol construct, carrying every field from every supported
protocol version, so application code sees a single set of types regardless of
the negotiated version. Per-field docstrings note version availability. The
`mcp_types.v*` surface packages carry the schema-exact wire shapes.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Generic, Literal, TypeAlias, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FileUrl,
    TypeAdapter,
    model_validator,
)
from pydantic.alias_generators import to_camel
from typing_extensions import NotRequired, Self, TypedDict

from mcp_types.jsonrpc import RequestId

DEFAULT_NEGOTIATED_VERSION: Final[str] = "2025-03-26"
"""Protocol version the server must assume when the client specifies none, per the MCP spec.

See https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#protocol-version-header.
"""

ProgressToken = str | int
"""A progress token, used to associate progress notifications with the original request."""
Role = Literal["user", "assistant"]
"""The sender or recipient of messages and data in a conversation."""

IconTheme = Literal["light", "dark"]
"""Theme an icon is designed for. Wire values of `Icon.theme` (2025-11-25+)."""


class MCPModel(BaseModel):
    """Base class for all MCP protocol types."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Meta: TypeAlias = dict[str, Any]

PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
"""Reserved request `_meta` key: the MCP protocol version for this request (2026-07-28).

SDK-managed; for HTTP its value must match the `MCP-Protocol-Version` header.
"""

CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
"""Reserved request `_meta` key: the client `Implementation` (2026-07-28). SDK-managed."""

CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
"""Reserved request `_meta` key: per-request `ClientCapabilities` (2026-07-28). SDK-managed."""

LOG_LEVEL_META_KEY = "io.modelcontextprotocol/logLevel"
"""Reserved request `_meta` key: desired log level for this request (2026-07-28).

Deprecated (with the rest of logging) by SEP-2577 in the same revision that
introduces it. If absent, the server must not send log notifications.
"""


class RequestParamsMeta(TypedDict, extra_items=Any):
    """The `_meta` object on request params (schema name: `RequestMetaObject`).

    An open map: arbitrary keys round-trip via `extra_items=Any`. Read or set
    the reserved `io.modelcontextprotocol/*` keys via the `*_META_KEY` constants.
    """

    progress_token: NotRequired[ProgressToken]
    """An opaque token requesting out-of-band progress notifications (notifications/progress)
    for this request; it is attached to any subsequent notifications. The receiver is not
    obligated to provide them."""


class RequestParams(MCPModel):
    meta: RequestParamsMeta | None = Field(alias="_meta", default=None)
    """Metadata reserved by MCP for protocol-level concerns (wire name `_meta`).

    Carries the optional progress token and, on 2026-07-28+ sessions, the
    reserved `io.modelcontextprotocol/*` keys. Required on the wire for
    2026-07-28+ client requests; the session layer supplies the reserved
    entries, so code sending through an SDK session leaves this unset.
    """


class PaginatedRequestParams(RequestParams):
    cursor: str | None = None
    """Opaque pagination position; if provided, the server should return results starting after it."""


class NotificationParams(MCPModel):
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


RequestParamsT = TypeVar("RequestParamsT", bound=RequestParams | dict[str, Any] | None)
NotificationParamsT = TypeVar("NotificationParamsT", bound=NotificationParams | dict[str, Any] | None)
MethodT = TypeVar("MethodT", bound=str)


class Request(MCPModel, Generic[RequestParamsT, MethodT]):
    """Base class for JSON-RPC requests.

    The JSON-RPC envelope (`jsonrpc`, `id`) is attached by the session layer
    (see `mcp_types.jsonrpc`), not carried here.
    """

    method: MethodT
    params: RequestParamsT


class PaginatedRequest(Request[PaginatedRequestParams | None, MethodT], Generic[MethodT]):
    """Base class for paginated requests."""

    params: PaginatedRequestParams | None = None
    """Pagination params. Required on the 2026-07-28+ wire (because `_meta` is);
    the session layer materializes it there. Optional on earlier versions."""


class Notification(MCPModel, Generic[NotificationParamsT, MethodT]):
    """Base class for JSON-RPC notifications."""

    method: MethodT
    params: NotificationParamsT


ResultType = Literal["complete", "input_required"] | str
"""Tags a `Result` so the client knows how to parse it (2026-07-28).

"complete" means the result is final; "input_required" means it is an
`InputRequiredResult`. The union is open (the tasks extension reserves "task").
Absent `resultType` is equivalent to "complete".
"""


class Result(MCPModel):
    """Base class for JSON-RPC results.

    `result_type` is declared per concrete subclass, not here, because defaults
    differ: most results default to "complete", `EmptyResult` defaults to None
    (so it dumps as `{}`; some peer SDKs strict-validate empty results), and
    `InputRequiredResult` carries a literal.
    """

    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class PaginatedResult(Result):
    next_cursor: str | None = None
    """Opaque pagination position after the last returned result; if present, more may be available."""


class CacheableResult(Result):
    """Base class for results that carry client-side caching directives (2026-07-28).

    Both fields are required on the 2026-07-28 wire. The SDK defaults to
    `ttl_ms=0` (immediately stale) and `cache_scope="private"` so a handler
    that doesn't set them still produces a valid 2026-07-28 result without
    accidentally enabling shared caching.
    """

    ttl_ms: Annotated[int, Field(ge=0)] = 0
    """How long (ms) the client MAY cache this response, analogous to HTTP
    `Cache-Control: max-age`. 0 means immediately stale."""

    cache_scope: Literal["public", "private"] = "private"
    """Analogous to HTTP `Cache-Control: public` vs `private`: "public" allows
    shared caches to serve the response to any user; "private" forbids that."""


class EmptyResult(Result):
    """A result that indicates success but carries no data.

    `result_type` defaults to None so this dumps as `{}`: deployed TypeScript
    and Rust SDK peers (clients and servers) validate empty results strictly
    and reject extra keys. The 2026-07-28 schema requires `resultType`, so code
    answering an empty result on a 2026-07-28+ session must pass
    `result_type="complete"`.
    """

    result_type: ResultType | None = None
    """None keeps the dump empty; see the class docstring."""


class BaseMetadata(MCPModel):
    """Base class for entities with a programmatic name and an optional display title."""

    name: str
    """Intended for programmatic or logical use, but used as a display name in past
    specs or fallback (if title isn't present)."""

    title: str | None = None
    """Human-readable display name for UI and end-user contexts.

    If not provided, `name` should be used for display (except for Tool, where
    `annotations.title` takes precedence over `name`).
    """


class Icon(MCPModel):
    """An optionally-sized icon for display in a user interface (2025-11-25+)."""

    src: str
    """A standard URI pointing to an icon resource (`http(s):` or `data:`).

    Consumers SHOULD ensure icon URLs come from a trusted domain and SHOULD
    take appropriate precautions when consuming SVGs (which can contain script).
    """

    mime_type: str | None = None
    """Optional MIME type override if the source MIME type is missing or generic."""

    sizes: list[str] | None = None
    """Optional sizes this icon is available in: WxH (e.g. `"48x48"`) or `"any"`.
    If not provided, assume the icon can be used at any size."""

    theme: IconTheme | None = None
    """The theme this icon is designed for. If not provided, assume any theme."""


class Implementation(BaseMetadata):
    """Describes the name and version of an MCP implementation (`clientInfo` / `serverInfo`)."""

    version: str
    description: str | None = None
    """An optional human-readable description of what this implementation does."""

    website_url: str | None = None
    """An optional URL of the website for this implementation."""

    icons: list[Icon] | None = None
    """Optional set of sized icons that the client can display in a user interface."""


class RootsCapability(MCPModel):
    """Capability for root operations.

    Deprecated in protocol 2026-07-28 (SEP-2577) but still carried there as an
    empty object (`list_changed` exists only through 2025-11-25).
    """

    list_changed: bool | None = None
    """Whether the client supports notifications for changes to the roots list."""


class SamplingContextCapability(MCPModel):
    """Support for non-'none' `includeContext` values during sampling.

    SOFT-DEPRECATED: new implementations should use the tools parameter instead.
    """


class SamplingToolsCapability(MCPModel):
    """The client supports the tools and toolChoice parameters in sampling requests."""


class FormElicitationCapability(MCPModel):
    """Capability for form mode elicitation."""


class UrlElicitationCapability(MCPModel):
    """Capability for URL mode elicitation (2025-11-25+)."""


class ElicitationCapability(MCPModel):
    """Capability for elicitation operations.

    Clients must support at least one mode (form or url).
    """

    form: FormElicitationCapability | None = None
    """Present if the client supports form mode elicitation."""

    url: UrlElicitationCapability | None = None
    """Present if the client supports URL mode elicitation (2025-11-25 and later)."""


class SamplingCapability(MCPModel):
    """Sampling capability structure. Deprecated in 2026-07-28 (SEP-2577); shape unchanged."""

    context: SamplingContextCapability | None = None
    """Present if the client supports non-'none' `includeContext` values.
    SOFT-DEPRECATED: new implementations should use the tools parameter instead."""
    tools: SamplingToolsCapability | None = None
    """Present if the client supports the tools and toolChoice sampling parameters."""


class TasksListCapability(MCPModel):
    """Capability for tasks listing operations (2025-11-25 only)."""


class TasksCancelCapability(MCPModel):
    """Capability for tasks cancel operations (2025-11-25 only)."""


class TasksCreateMessageCapability(MCPModel):
    """Capability for task-augmented sampling/createMessage requests (2025-11-25 only)."""


class TasksSamplingCapability(MCPModel):
    """Capability for task-augmented sampling operations (2025-11-25 only)."""

    create_message: TasksCreateMessageCapability | None = None


class TasksCreateElicitationCapability(MCPModel):
    """Capability for task-augmented elicitation/create requests (2025-11-25 only)."""


class TasksElicitationCapability(MCPModel):
    """Capability for task-augmented elicitation operations (2025-11-25 only)."""

    create: TasksCreateElicitationCapability | None = None


class ClientTasksRequestsCapability(MCPModel):
    """Specifies which request types the client can augment with tasks (2025-11-25 only)."""

    sampling: TasksSamplingCapability | None = None
    elicitation: TasksElicitationCapability | None = None


class ClientTasksCapability(MCPModel):
    """Capability for client tasks operations (2025-11-25 only)."""

    list: TasksListCapability | None = None
    cancel: TasksCancelCapability | None = None
    requests: ClientTasksRequestsCapability | None = None


class ClientCapabilities(MCPModel):
    """Capabilities a client may support.

    Not a closed set: any client can define additional capabilities. Sent once in
    `initialize` through 2025-11-25; per-request in `_meta` on 2026-07-28.
    """

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the client supports."""
    sampling: SamplingCapability | None = None
    """Present if the client supports sampling from an LLM."""
    elicitation: ElicitationCapability | None = None
    """Present if the client supports elicitation from the user."""
    roots: RootsCapability | None = None
    """Present if the client supports listing roots."""
    extensions: dict[str, dict[str, Any]] | None = None
    """MCP extensions the client supports (2026-07-28). Keys are extension
    identifiers; values are per-extension settings (empty object = no settings)."""
    tasks: ClientTasksCapability | None = None
    """Present if the client supports task-augmented requests (2025-11-25 only)."""


class UnsupportedProtocolVersionErrorData(MCPModel):
    """Error data for the -32022 unsupported-protocol-version error (2026-07-28)."""

    supported: list[str]
    """Protocol versions the server supports; the client should pick one and retry."""

    requested: str


class MissingRequiredClientCapabilityErrorData(MCPModel):
    """Error data for the -32021 missing-required-client-capability error (2026-07-28)."""

    required_capabilities: ClientCapabilities
    """The capabilities the server requires from the client to process this request."""


class PromptsCapability(MCPModel):
    """Capability for prompts operations."""

    list_changed: bool | None = None
    """Whether this server supports notifications for changes to the prompt list."""


class ResourcesCapability(MCPModel):
    """Capability for resources operations."""

    subscribe: bool | None = None
    """Whether this server supports subscribing to resource updates."""
    list_changed: bool | None = None
    """Whether this server supports notifications for changes to the resource list."""


class ToolsCapability(MCPModel):
    """Capability for tools operations."""

    list_changed: bool | None = None
    """Whether this server supports notifications for changes to the tool list."""


class LoggingCapability(MCPModel):
    """Capability for logging operations."""


class CompletionsCapability(MCPModel):
    """Capability for completions operations."""


class TasksCallCapability(MCPModel):
    """Capability for task-augmented tools/call requests (2025-11-25 only)."""


class TasksToolsCapability(MCPModel):
    """Capability for task-augmented tool operations (2025-11-25 only)."""

    call: TasksCallCapability | None = None


class ServerTasksRequestsCapability(MCPModel):
    """Specifies which request types the server can augment with tasks (2025-11-25 only)."""

    tools: TasksToolsCapability | None = None


class ServerTasksCapability(MCPModel):
    """Capability for server tasks operations (2025-11-25 only)."""

    list: TasksListCapability | None = None
    cancel: TasksCancelCapability | None = None
    requests: ServerTasksRequestsCapability | None = None


class ServerCapabilities(MCPModel):
    """Capabilities that a server may support. Not a closed set."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the server supports."""

    logging: LoggingCapability | None = None
    """Present if the server supports sending log messages to the client.
    Deprecated in 2026-07-28 (SEP-2577)."""

    prompts: PromptsCapability | None = None
    """Present if the server offers any prompt templates."""

    resources: ResourcesCapability | None = None
    """Present if the server offers any resources to read."""

    tools: ToolsCapability | None = None
    """Present if the server offers any tools to call."""

    completions: CompletionsCapability | None = None
    """Present if the server offers autocompletion suggestions for prompts and resources."""

    extensions: dict[str, dict[str, Any]] | None = None
    """MCP extensions the server supports (2026-07-28). Keys are extension
    identifiers; values are per-extension settings (empty object = no settings)."""

    tasks: ServerTasksCapability | None = None
    """Present if the server supports task-augmented requests (2025-11-25 only)."""


class InitializeRequestParams(RequestParams):
    """Parameters for the `initialize` request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    protocol_version: str
    """The latest version of the Model Context Protocol that the client supports."""
    capabilities: ClientCapabilities
    client_info: Implementation


class InitializeRequest(Request[InitializeRequestParams, Literal["initialize"]]):
    """Sent from the client when it first connects, asking the server to begin initialization.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    On 2026-07-28 the handshake is `server/discover` plus per-request `_meta`.
    """

    method: Literal["initialize"] = "initialize"
    params: InitializeRequestParams


class InitializeResult(Result):
    """After receiving an initialize request from the client, the server sends this response.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    protocol_version: str
    """The version of the Model Context Protocol that the server wants to use.
    If the client cannot support this version, it MUST disconnect."""
    capabilities: ServerCapabilities
    server_info: Implementation
    instructions: str | None = None
    """Instructions describing how to use the server, e.g. added to a system prompt
    to improve the LLM's understanding of available tools and resources."""


class InitializedNotification(Notification[NotificationParams | None, Literal["notifications/initialized"]]):
    """Sent from the client after initialization has finished.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["notifications/initialized"] = "notifications/initialized"
    params: NotificationParams | None = None


class PingRequest(Request[RequestParams | None, Literal["ping"]]):
    """A ping, issued by either the server or the client, to check that the other party is
    still alive. The receiver must promptly respond, or else may be disconnected.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["ping"] = "ping"
    params: RequestParams | None = None


class DiscoverRequest(Request[RequestParams | None, Literal["server/discover"]]):
    """Asks the server to advertise its supported protocol versions, capabilities,
    and other metadata (2026-07-28).

    Servers speaking 2026-07-28 MUST implement this; clients MAY call it but are
    not required to (version negotiation can also happen via per-request `_meta`).
    """

    method: Literal["server/discover"] = "server/discover"
    params: RequestParams | None = None
    """Required on the 2026-07-28 wire (for `_meta`); the session layer materializes it."""


class DiscoverResult(CacheableResult):
    """The result returned by the server for a `server/discover` request (2026-07-28)."""

    supported_versions: list[str]
    """MCP protocol versions this server supports; the client should pick one for subsequent requests."""

    capabilities: ServerCapabilities

    server_info: Implementation

    instructions: str | None = None
    """Natural-language guidance describing the server and its features, e.g. for
    a system prompt. Should not duplicate information already in tool descriptions."""

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; required on the 2026-07-28 wire,
    ignored by older peers, and defaulted on inbound bodies that omit it."""


# Tasks: introduced in 2025-11-25, removed from the core spec in 2026-07-28 (now an
# extension). Types-only: their methods are not in the unions below, so never dispatched.


class ToolExecution(MCPModel):
    """Execution-related properties for a tool (2025-11-25 only)."""

    task_support: Literal["forbidden", "optional", "required"] | None = None
    """Whether this tool supports task-augmented execution. Absent means "forbidden"."""


class TaskMetadata(MCPModel):
    """Metadata for augmenting a request with task execution (the `task` params field; 2025-11-25 only)."""

    ttl: int | None = None
    """Requested duration in milliseconds to retain task from creation."""


class RelatedTaskMetadata(MCPModel):
    """Associates a message with a task, via `_meta["io.modelcontextprotocol/related-task"]` (2025-11-25 only)."""

    task_id: str


TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]
"""The status of a task (2025-11-25 only)."""


class Task(MCPModel):
    """Data associated with a task (2025-11-25 only)."""

    task_id: str

    status: TaskStatus

    status_message: str | None = None
    """Optional human-readable message describing the current task state."""

    created_at: str
    """ISO 8601 timestamp when the task was created."""

    last_updated_at: str
    """ISO 8601 timestamp when the task was last updated."""

    ttl: int | None
    """Actual retention duration from creation in milliseconds, null for unlimited."""

    poll_interval: int | None = None
    """Suggested polling interval in milliseconds."""


class CreateTaskResult(Result):
    """A response to a task-augmented request (2025-11-25 only)."""

    task: Task


class GetTaskRequestParams(RequestParams):
    task_id: str


class GetTaskRequest(Request[GetTaskRequestParams, Literal["tasks/get"]]):
    """A request to retrieve the state of a task (2025-11-25 only)."""

    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


class GetTaskResult(Result, Task):
    """The response to a tasks/get request (2025-11-25 only)."""


class CancelTaskRequestParams(RequestParams):
    task_id: str


class CancelTaskRequest(Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    """A request to cancel a task (2025-11-25 only)."""

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class CancelTaskResult(Result, Task):
    """The response to a tasks/cancel request (2025-11-25 only)."""


class TaskStatusNotificationParams(NotificationParams, Task):
    """Parameters for a `notifications/tasks/status` notification."""


class TaskStatusNotification(Notification[TaskStatusNotificationParams, Literal["notifications/tasks/status"]]):
    """An optional notification informing the requestor that a task's status has changed (2025-11-25 only)."""

    method: Literal["notifications/tasks/status"] = "notifications/tasks/status"
    params: TaskStatusNotificationParams


class GetTaskPayloadRequestParams(RequestParams):
    """Parameters for a tasks/result request."""

    task_id: str


class GetTaskPayloadRequest(Request[GetTaskPayloadRequestParams, Literal["tasks/result"]]):
    """A request to retrieve the result of a completed task (2025-11-25 only)."""

    method: Literal["tasks/result"] = "tasks/result"
    params: GetTaskPayloadRequestParams


class GetTaskPayloadResult(Result):
    """The response to a tasks/result request (2025-11-25 only).

    The structure matches the result type of the original request. The payload
    arrives as extra wire fields, which `MCPModel` does not retain; validate the
    response into the original request's result type (e.g. `CallToolResult`)
    instead of this class.
    """


class ListTasksRequest(PaginatedRequest[Literal["tasks/list"]]):
    """A request to retrieve a list of tasks (2025-11-25 only)."""

    method: Literal["tasks/list"] = "tasks/list"


class ListTasksResult(PaginatedResult):
    """The response to a tasks/list request (2025-11-25 only)."""

    tasks: list[Task]


class ProgressNotificationParams(NotificationParams):
    """Parameters for progress notifications."""

    progress_token: ProgressToken
    """The token from the original request, associating this notification with it."""
    progress: float
    """Progress thus far; should increase on every update, even if the total is unknown."""
    total: float | None = None
    """Total number of items to process (or total progress required), if known."""
    message: str | None = None
    """Optional human-readable progress information."""


class ProgressNotification(Notification[ProgressNotificationParams, Literal["notifications/progress"]]):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    method: Literal["notifications/progress"] = "notifications/progress"
    params: ProgressNotificationParams


class ListResourcesRequest(PaginatedRequest[Literal["resources/list"]]):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"] = "resources/list"


class Annotations(MCPModel):
    """Optional annotations the client can use to inform how objects are used or displayed."""

    audience: list[Role] | None = None
    """Who the intended audience is, e.g. `["user", "assistant"]`."""

    priority: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    """How important this data is for operating the server: 1 means effectively
    required, 0 means entirely optional."""

    last_modified: str | None = None
    """ISO 8601 timestamp of when the item was last modified."""


class Resource(BaseMetadata):
    """A known resource that the server is capable of reading."""

    uri: str
    """The URI of this resource."""

    description: str | None = None
    """A description of what this resource represents."""

    mime_type: str | None = None
    """The MIME type of this resource, if known."""

    size: int | None = None
    """Raw content size in bytes (before base64 encoding or tokenization), if known.
    Lets hosts display file sizes and estimate context window usage."""

    icons: list[Icon] | None = None
    """Optional set of sized icons that the client can display in a user interface."""

    annotations: Annotations | None = None
    """Optional annotations for the client."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ResourceTemplate(BaseMetadata):
    """A template description for resources available on the server."""

    uri_template: str
    """A URI template (according to RFC 6570) that can be used to construct resource URIs."""

    description: str | None = None
    """A description of what this template is for."""

    mime_type: str | None = None
    """The MIME type of all matching resources; include only if they all share the same type."""

    icons: list[Icon] | None = None
    """An optional set of sized icons that the client can display in a user interface."""

    annotations: Annotations | None = None
    """Optional annotations for the client."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ListResourcesResult(PaginatedResult, CacheableResult):
    """The server's response to a resources/list request from the client."""

    resources: list[Resource]
    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class ListResourceTemplatesRequest(PaginatedRequest[Literal["resources/templates/list"]]):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"] = "resources/templates/list"


class ListResourceTemplatesResult(PaginatedResult, CacheableResult):
    """The server's response to a resources/templates/list request from the client."""

    resource_templates: list[ResourceTemplate]
    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class InputResponseRequestParams(RequestParams):
    """Base params for client requests that can carry responses to a server's
    input requests (2026-07-28 multi-round-trip flow).

    When a request returns an `InputRequiredResult`, the client retries the
    original request with these fields populated.
    """

    input_responses: InputResponses | None = None
    """Responses to the server's `InputRequiredResult.input_requests`, keyed identically."""
    request_state: str | None = None
    """Opaque state from the `InputRequiredResult`, passed back verbatim on retry."""


class ReadResourceRequestParams(InputResponseRequestParams):
    uri: str
    """The URI of the resource; any protocol, interpreted by the server."""


class ReadResourceRequest(Request[ReadResourceRequestParams, Literal["resources/read"]]):
    """Sent from the client to the server, to read a specific resource URI."""

    method: Literal["resources/read"] = "resources/read"
    params: ReadResourceRequestParams


class ResourceContents(MCPModel):
    """The contents of a specific resource or sub-resource."""

    uri: str
    """The URI of this resource."""
    mime_type: str | None = None
    """The MIME type of this resource, if known."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class TextResourceContents(ResourceContents):
    """Text contents of a resource."""

    text: str
    """The text of the item; only for items representable as text (not binary data)."""


class BlobResourceContents(ResourceContents):
    """Binary contents of a resource."""

    blob: str
    """A base64-encoded string representing the binary data of the item."""


class ReadResourceResult(CacheableResult):
    """The server's response to a resources/read request from the client."""

    contents: list[TextResourceContents | BlobResourceContents]
    """The contents of the resource or sub-resources that were read."""

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class ResourceListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/resources/list_changed"]]
):
    """Optional server notification that the list of readable resources has changed.

    May be sent spontaneously through 2025-11-25; on 2026-07-28 sessions the
    client must opt in via `subscriptions/listen`.
    """

    method: Literal["notifications/resources/list_changed"] = "notifications/resources/list_changed"
    params: NotificationParams | None = None


class SubscribeRequestParams(RequestParams):
    """Parameters for subscribing to a resource.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    uri: str
    """The URI of the resource to subscribe to; any protocol, interpreted by the server."""


class SubscribeRequest(Request[SubscribeRequestParams, Literal["resources/subscribe"]]):
    """Requests resources/updated notifications whenever a particular resource changes.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    On 2026-07-28 use `subscriptions/listen` instead.
    """

    method: Literal["resources/subscribe"] = "resources/subscribe"
    params: SubscribeRequestParams


class UnsubscribeRequestParams(RequestParams):
    """Parameters for a resources/unsubscribe request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    uri: str
    """The URI of the resource to unsubscribe from."""


class UnsubscribeRequest(Request[UnsubscribeRequestParams, Literal["resources/unsubscribe"]]):
    """Cancels resources/updated notifications from a previous resources/subscribe request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    On 2026-07-28 use `subscriptions/listen` instead.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    params: UnsubscribeRequestParams


class ResourceUpdatedNotificationParams(NotificationParams):
    uri: str
    """The URI of the updated resource; may be a sub-resource of the one subscribed to."""


class ResourceUpdatedNotification(
    Notification[ResourceUpdatedNotificationParams, Literal["notifications/resources/updated"]]
):
    """Server notification that a resource has changed and may need to be read again.

    Only sent if the client subscribed: via `resources/subscribe` through
    2025-11-25, or `subscriptions/listen` on 2026-07-28.
    """

    method: Literal["notifications/resources/updated"] = "notifications/resources/updated"
    params: ResourceUpdatedNotificationParams


class SubscriptionFilter(MCPModel):
    """The set of notification types a client opts in to via `subscriptions/listen` (2026-07-28).

    Each type is opt-in; the server MUST NOT send types not requested here.
    Echoed back in `notifications/subscriptions/acknowledged` as the subset the
    server agreed to honor. Extensions merge additional keys (e.g. `taskIds`),
    so unknown keys round-trip.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    tools_list_changed: bool | None = None
    """If true, receive notifications/tools/list_changed."""

    prompts_list_changed: bool | None = None
    """If true, receive notifications/prompts/list_changed."""

    resources_list_changed: bool | None = None
    """If true, receive notifications/resources/list_changed."""

    resource_subscriptions: list[str] | None = None
    """Subscribe to notifications/resources/updated for these resource URIs."""


class SubscriptionsListenRequestParams(RequestParams):
    notifications: SubscriptionFilter
    """The notifications the client opts in to on this stream."""


class SubscriptionsListenRequest(Request[SubscriptionsListenRequestParams, Literal["subscriptions/listen"]]):
    """Opens a long-lived channel for receiving notifications outside the context
    of a specific request (2026-07-28).
    """

    method: Literal["subscriptions/listen"] = "subscriptions/listen"
    params: SubscriptionsListenRequestParams


class SubscriptionsAcknowledgedNotificationParams(NotificationParams):
    notifications: SubscriptionFilter
    """The subset of requested notification types the server agreed to honor.
    Unsupported types are omitted."""


class SubscriptionsAcknowledgedNotification(
    Notification[
        SubscriptionsAcknowledgedNotificationParams,
        Literal["notifications/subscriptions/acknowledged"],
    ]
):
    """First message on a `subscriptions/listen` stream: acknowledges the
    subscription and reports which notification types the server will honor (2026-07-28).
    """

    method: Literal["notifications/subscriptions/acknowledged"] = "notifications/subscriptions/acknowledged"
    params: SubscriptionsAcknowledgedNotificationParams


class SubscriptionsListenResult(Result):
    """Signals that a `subscriptions/listen` stream has ended gracefully (2026-07-28).

    Because the listen stream is long-lived, this result is sent only when the
    server tears the subscription down (for example during shutdown); an abrupt
    transport close carries no response. The body is otherwise empty: the
    `_meta["io.modelcontextprotocol/subscriptionId"]` key is required on the
    wire and equals the JSON-RPC id of the originating `subscriptions/listen`
    request.
    """

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class ListPromptsRequest(PaginatedRequest[Literal["prompts/list"]]):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    method: Literal["prompts/list"] = "prompts/list"


class PromptArgument(BaseMetadata):
    """Describes an argument that a prompt can accept."""

    description: str | None = None
    """A human-readable description of the argument."""
    required: bool | None = None
    """Whether this argument must be provided."""


class Prompt(BaseMetadata):
    """A prompt or prompt template that the server offers."""

    description: str | None = None
    """An optional description of what this prompt provides."""
    arguments: list[PromptArgument] | None = None
    """A list of arguments to use for templating the prompt."""
    icons: list[Icon] | None = None
    """An optional list of icons for this prompt."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ListPromptsResult(PaginatedResult, CacheableResult):
    """The server's response to a prompts/list request from the client."""

    prompts: list[Prompt]
    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class GetPromptRequestParams(InputResponseRequestParams):
    name: str
    """The name of the prompt or prompt template."""
    arguments: dict[str, str] | None = None
    """Arguments to use for templating the prompt."""


class GetPromptRequest(Request[GetPromptRequestParams, Literal["prompts/get"]]):
    """Used by the client to get a prompt provided by the server."""

    method: Literal["prompts/get"] = "prompts/get"
    params: GetPromptRequestParams


class TextContent(MCPModel):
    """Text provided to or from an LLM."""

    type: Literal["text"] = "text"
    text: str
    """The text content of the message."""
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ImageContent(MCPModel):
    """An image provided to or from an LLM."""

    type: Literal["image"] = "image"
    data: str
    """The base64-encoded image data."""
    mime_type: str
    """The MIME type of the image. Different providers may support different image types."""
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class AudioContent(MCPModel):
    """Audio provided to or from an LLM."""

    type: Literal["audio"] = "audio"
    data: str
    """The base64-encoded audio data."""
    mime_type: str
    """The MIME type of the audio. Different providers may support different audio types."""
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ToolUseContent(MCPModel):
    """An assistant's request to invoke a tool during sampling (2025-11-25+).

    Appears in `sampling/createMessage` results and replayed assistant messages.
    The server should execute the tool and return a `ToolResultContent` in the
    next user message. Deprecated in 2026-07-28 (SEP-2577).
    """

    type: Literal["tool_use"] = "tool_use"
    """Discriminator for tool use content."""

    name: str
    """The name of the tool to invoke. Must match a tool name from the request's tools array."""

    id: str
    """Unique identifier for this tool call, used to correlate with ToolResultContent."""

    input: dict[str, Any]
    """Arguments to pass to the tool. Must conform to the tool's inputSchema."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """Optional metadata. Clients SHOULD preserve this in subsequent sampling
    requests to enable caching optimizations."""


class ToolResultContent(MCPModel):
    """The result of a tool use, provided by the user back to the assistant (2025-11-25+).

    Appears in sampling messages as a response to a `ToolUseContent` block.
    Requires the `sampling.tools` client capability. Deprecated in 2026-07-28 (SEP-2577).
    """

    type: Literal["tool_result"] = "tool_result"
    """Discriminator for tool result content."""

    tool_use_id: str
    """The `id` of the `ToolUseContent` this result corresponds to."""

    content: list[ContentBlock] = []
    """The unstructured result content (same format as `CallToolResult.content`)."""

    structured_content: Any = None
    """An optional structured result value. Any JSON value on 2026-07-28;
    restricted to a JSON object on 2025-11-25."""

    is_error: bool | None = None
    """Whether the tool use resulted in an error. Absent is equivalent to false."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """Optional metadata. Clients SHOULD preserve this in subsequent sampling
    requests to enable caching optimizations."""


SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent
"""Content block types allowed in sampling messages.

This is the widest (2025-11-25+) membership; older sessions allow only a subset
on the wire. Serialization never narrows a value to fit; version gating is the
session layer's responsibility. Deprecated in 2026-07-28 (SEP-2577).
"""

SamplingContent: TypeAlias = TextContent | ImageContent | AudioContent
"""Basic content types for sampling responses (without tool use).

Used for backwards-compatible CreateMessageResult when tools are not used.
"""


class SamplingMessage(MCPModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """A single content block or an array, for multi-modal messages and tool interactions."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """The content as a list, whether it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class EmbeddedResource(MCPModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    type: Literal["resource"] = "resource"
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ResourceLink(Resource):
    """A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    type: Literal["resource_link"] = "resource_link"


ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
"""A content block that can be used in prompts and tool results."""


class PromptMessage(MCPModel):
    """Describes a message returned as part of a prompt.

    Similar to `SamplingMessage`, but also supports embedded resources.
    """

    role: Role
    content: ContentBlock


class GetPromptResult(Result):
    """The server's response to a prompts/get request from the client."""

    description: str | None = None
    """An optional description for the prompt."""
    messages: list[PromptMessage]
    """The messages composing the prompt, in the order they should be presented."""

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class PromptListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/prompts/list_changed"]]
):
    """Optional server notification that the list of offered prompts has changed.

    May be sent spontaneously through 2025-11-25; on 2026-07-28 sessions the
    client must opt in via `subscriptions/listen`.
    """

    method: Literal["notifications/prompts/list_changed"] = "notifications/prompts/list_changed"
    params: NotificationParams | None = None


class ListToolsRequest(PaginatedRequest[Literal["tools/list"]]):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"] = "tools/list"


class ToolAnnotations(MCPModel):
    """Additional properties describing a Tool to clients.

    All properties are hints, not guaranteed to faithfully describe tool
    behavior. Clients should never make tool-use decisions based on
    annotations received from untrusted servers.
    """

    title: str | None = None
    """A human-readable title for the tool."""

    read_only_hint: bool | None = None
    """If true, the tool does not modify its environment. Default: false."""

    destructive_hint: bool | None = None
    """If true, the tool may perform destructive (rather than only additive) updates.
    Meaningful only when `read_only_hint` is false. Default: true."""

    idempotent_hint: bool | None = None
    """If true, repeated calls with the same arguments have no additional effect.
    Meaningful only when `read_only_hint` is false. Default: false."""

    open_world_hint: bool | None = None
    """If true, the tool may interact with an "open world" of external entities
    (e.g. web search); if false, its domain is closed (e.g. memory). Default: true."""


class Tool(BaseMetadata):
    """Definition for a tool the client can call."""

    description: str | None = None
    """A human-readable description of the tool."""
    input_schema: dict[str, Any]
    """A JSON Schema object defining the expected parameters for the tool.

    `type: "object"` is required at the root. 2026-07-28 allows any JSON Schema
    2020-12 keyword; earlier versions define only `type`/`properties`/`required`.
    """
    execution: ToolExecution | None = None
    """Execution-related properties (2025-11-25 only; removed in 2026-07-28)."""
    output_schema: dict[str, Any] | None = None
    """An optional JSON Schema object defining the structure of the tool's output
    returned in the `structured_content` field of a `CallToolResult`.

    Restricted to `type: "object"` at the root through 2025-11-25; any valid
    JSON Schema 2020-12 on 2026-07-28.
    """
    icons: list[Icon] | None = None
    """Optional set of sized icons for display (2025-11-25+)."""
    annotations: ToolAnnotations | None = None
    """Optional additional tool information.
    Display-name precedence: `title`, `annotations.title`, then `name`."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ListToolsResult(PaginatedResult, CacheableResult):
    """The server's response to a tools/list request from the client."""

    tools: list[Tool]

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class CallToolRequestParams(InputResponseRequestParams):
    name: str
    arguments: dict[str, Any] | None = None
    task: TaskMetadata | None = None
    """If specified, the caller requests task-augmented execution (2025-11-25 only)."""


class CallToolRequest(Request[CallToolRequestParams, Literal["tools/call"]]):
    """Used by the client to invoke a tool provided by the server."""

    method: Literal["tools/call"] = "tools/call"
    params: CallToolRequestParams


class CallToolResult(Result):
    """The server's response to a tool call.

    Errors that originate from the tool SHOULD be reported inside the result
    with `is_error` set to true, not as an MCP protocol-level error, so the LLM
    can see and self-correct. Errors in finding the tool, or any other
    exceptional condition, should be reported as an MCP error response.
    """

    content: list[ContentBlock]
    """A list of content objects that represent the unstructured result of the tool call."""
    structured_content: Any = None
    """An optional JSON value representing the structured result of the tool call.

    Any JSON value on 2026-07-28; restricted to a JSON object on 2025-06-18 and
    2025-11-25.
    """
    is_error: bool = False
    """Whether the tool call ended in an error."""

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class ToolListChangedNotification(Notification[NotificationParams | None, Literal["notifications/tools/list_changed"]]):
    """Optional server notification that the list of offered tools has changed.

    May be sent spontaneously through 2025-11-25; on 2026-07-28 sessions the
    client must opt in via `subscriptions/listen`.
    """

    method: Literal["notifications/tools/list_changed"] = "notifications/tools/list_changed"
    params: NotificationParams | None = None


LoggingLevel = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
"""The severity of a log message.

These map to syslog severities (RFC-5424 section 6.2.1). Logging is deprecated
in 2026-07-28 (SEP-2577); the level scale is unchanged across versions.
"""


class SetLevelRequestParams(RequestParams):
    """Parameters for setting the logging level.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    level: LoggingLevel
    """The level of logging that the client wants to receive from the server.
    The server should send all logs at this level and higher (more severe)."""


class SetLevelRequest(Request[SetLevelRequestParams, Literal["logging/setLevel"]]):
    """A request from the client to the server, to enable or adjust logging.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    On 2026-07-28 the client opts in per-request via `_meta` (`LOG_LEVEL_META_KEY`).
    """

    method: Literal["logging/setLevel"] = "logging/setLevel"
    params: SetLevelRequestParams


class LoggingMessageNotificationParams(NotificationParams):
    level: LoggingLevel
    """The severity of this log message."""
    logger: str | None = None
    """An optional name of the logger issuing this message."""
    data: Any
    """The data to log: any JSON-serializable value, such as a string message or an object."""


class LoggingMessageNotification(Notification[LoggingMessageNotificationParams, Literal["notifications/message"]]):
    """Notification of a log message passed from server to client.

    Through 2025-11-25 the client subscribes via `logging/setLevel`. On
    2026-07-28 the client opts in per-request via `_meta` (`LOG_LEVEL_META_KEY`)
    and the server MUST NOT send this without it. Deprecated in 2026-07-28 (SEP-2577).
    """

    method: Literal["notifications/message"] = "notifications/message"
    params: LoggingMessageNotificationParams


IncludeContext = Literal["none", "thisServer", "allServers"]
"""Scope of MCP-server context a sampling request asks the client to attach.

"thisServer" and "allServers" are deprecated (SEP-2596).
"""


class ModelHint(MCPModel):
    """Hints to use for model selection.

    Keys not declared here are up to the client to interpret. Deprecated in
    2026-07-28 (SEP-2577) with the rest of sampling.
    """

    name: str | None = None
    """A model-name hint. The client SHOULD treat it as a substring (e.g. `sonnet`
    matches `claude-3-5-sonnet-20241022`) and MAY map it to an equivalent model
    from another provider."""


class ModelPreferences(MCPModel):
    """The server's preferences for model selection, requested of the client during sampling.

    Expresses the server's priorities across cost, speed, and intelligence.
    Always advisory: the client MAY ignore them, and decides how to interpret
    and balance them against other considerations.

    Deprecated in 2026-07-28 (SEP-2577) with the rest of sampling.
    """

    hints: list[ModelHint] | None = None
    """Hints the client MUST evaluate in order (first match is taken). The client SHOULD
    prioritize these over the numeric priorities, but MAY use those for ambiguous matches."""

    cost_priority: float | None = None
    """How much to prioritize cost: 0 means not important, 1 means most important."""

    speed_priority: float | None = None
    """How much to prioritize sampling speed (latency): 0 means not important, 1 means most important."""

    intelligence_priority: float | None = None
    """How much to prioritize intelligence and capabilities: 0 means not important, 1 means most important."""


class ToolChoice(MCPModel):
    """Controls tool selection behavior for sampling requests (2025-11-25+).

    The client MUST return an error if this is received without the
    `sampling.tools` capability. Absent means `{"mode": "auto"}`.
    """

    mode: Literal["auto", "required", "none"] | None = None
    """Tool-use mode: "auto" = model decides (default); "required" = MUST use at
    least one tool before completing; "none" = MUST NOT use any tools."""


class CreateMessageRequestParams(RequestParams):
    messages: list[SamplingMessage]
    """The conversation to sample from."""
    model_preferences: ModelPreferences | None = None
    """The server's model selection preferences; the client MAY ignore them."""
    system_prompt: str | None = None
    """An optional system prompt the server wants to use for sampling."""
    include_context: IncludeContext | None = None
    """Request to attach context from MCP servers (including the caller) to the prompt;
    the client MAY ignore it. Default "none". "thisServer" and "allServers" are
    deprecated (SEP-2596)."""
    temperature: float | None = None
    max_tokens: int
    """The maximum number of tokens to sample, as requested by the server."""
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] | None = None
    """Optional metadata to pass through to the LLM provider. Provider-specific."""
    tools: list[Tool] | None = None
    """Tools the model may use during generation (2025-11-25+). Requires the
    `sampling.tools` client capability."""
    tool_choice: ToolChoice | None = None
    """Controls how the model uses tools (2025-11-25+). Requires the
    `sampling.tools` client capability."""
    task: TaskMetadata | None = None
    """If specified, the caller requests task-augmented execution (2025-11-25 only)."""


class CreateMessageRequest(Request[CreateMessageRequestParams, Literal["sampling/createMessage"]]):
    """A request from the server to sample an LLM via the client.

    The client has full discretion over which model to select and should inform
    the user before sampling (human in the loop). A standalone JSON-RPC request
    through 2025-11-25; on 2026-07-28 it is embedded in
    `InputRequiredResult.input_requests` instead. Deprecated in 2026-07-28 (SEP-2577).
    """

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    params: CreateMessageRequestParams


StopReason = Literal["endTurn", "stopSequence", "maxTokens", "toolUse"] | str
"""The reason why sampling stopped, if known.

An open union to allow provider-specific stop reasons. "toolUse" is 2025-11-25+.
"""


class CreateMessageResult(Result):
    """The client's response to a sampling/createMessage request from the server.

    This is the backwards-compatible version that returns single content (no arrays).
    Used when the request does not include tools.

    On 2026-07-28 this travels embedded in an `InputResponses` map rather than
    as a top-level JSON-RPC result. Deprecated in 2026-07-28 (SEP-2577).
    """

    role: Role
    """The role of the message sender (typically 'assistant' for LLM responses)."""
    content: SamplingContent
    """Response content. Single content block (text, image, or audio)."""
    model: str
    """The name of the model that generated the message."""
    stop_reason: StopReason | None = None
    """The reason why sampling stopped, if known."""


class CreateMessageResultWithTools(Result):
    """The client's response to a sampling/createMessage request when tools were provided.

    This version supports array content for tool use flows (2025-11-25 and later).
    """

    role: Role
    """The role of the message sender (typically 'assistant' for LLM responses)."""
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """A single content block or an array; may include ToolUseContent when stop_reason is 'toolUse'."""
    model: str
    """The name of the model that generated the message."""
    stop_reason: StopReason | None = None
    """Why sampling stopped, if known; 'toolUse' means the model wants to use a tool."""

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """The content as a list, whether it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class ResourceTemplateReference(MCPModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"] = "ref/resource"
    uri: str
    """The URI or URI template of the resource."""


# Not BaseMetadata: inheriting would reorder dump keys for existing callers.
class PromptReference(MCPModel):
    """Identifies a prompt."""

    type: Literal["ref/prompt"] = "ref/prompt"
    name: str
    """The name of the prompt or prompt template."""
    title: str | None = None
    """Human-readable display title. If not provided, `name` should be used for display."""


class CompletionArgument(MCPModel):
    """The argument's information for completion requests."""

    name: str
    """The name of the argument."""
    value: str
    """The value of the argument to use for completion matching."""


class CompletionContext(MCPModel):
    """Additional, optional context for completions."""

    arguments: dict[str, str] | None = None
    """Previously-resolved variables in a URI template or prompt."""


class CompleteRequestParams(RequestParams):
    ref: ResourceTemplateReference | PromptReference
    """The prompt or resource-template reference to complete against."""
    argument: CompletionArgument
    context: CompletionContext | None = None
    """Additional, optional context for completions."""


class CompleteRequest(Request[CompleteRequestParams, Literal["completion/complete"]]):
    """A request from the client to the server, to ask for completion options."""

    method: Literal["completion/complete"] = "completion/complete"
    params: CompleteRequestParams


class Completion(MCPModel):
    """Completion information."""

    values: list[str]
    """An array of completion values. Must not exceed 100 items."""
    total: int | None = None
    """Total completion options available; can exceed the number of values returned."""
    has_more: bool | None = None
    """Whether more completion options exist beyond those returned, even if the total is unknown."""


class CompleteResult(Result):
    """The server's response to a completion/complete request."""

    completion: Completion
    """The completion values, with optional total / has-more pagination hints."""

    result_type: ResultType = "complete"
    """See `ResultType`. Always serialized; older peers ignore it."""


class ListRootsRequest(Request[RequestParams | None, Literal["roots/list"]]):
    """Requests the list of root URIs (directories/files the server may operate on) from the client.

    A standalone JSON-RPC request through 2025-11-25; on 2026-07-28 it is
    embedded in `InputRequiredResult.input_requests`. Deprecated in 2026-07-28 (SEP-2577).
    """

    method: Literal["roots/list"] = "roots/list"
    params: RequestParams | None = None
    """Stays optional on 2026-07-28 (reserved client `_meta` keys do not apply
    to server-to-client payloads)."""


class Root(MCPModel):
    """Represents a root directory or file that the server can operate on.

    Deprecated in 2026-07-28 (SEP-2577) with the rest of roots.
    """

    uri: FileUrl
    """The URI identifying the root; must start with `file://` for now (future
    protocol versions may allow other schemes)."""
    name: str | None = None
    """Optional human-readable identifier for the root, for display or referencing."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification for notes on `_meta` usage."""


class ListRootsResult(Result):
    """The client's response to a roots/list request from the server.

    On 2026-07-28 this is carried as an `InputResponses` entry, not a JSON-RPC
    result. Deprecated in 2026-07-28 (SEP-2577).
    """

    roots: list[Root]


class RootsListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/roots/list_changed"]]
):
    """Client notification that the roots list has changed (any root added, removed,
    or modified); the server should re-request the list via ListRootsRequest.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["notifications/roots/list_changed"] = "notifications/roots/list_changed"
    params: NotificationParams | None = None


class CancelledNotificationParams(NotificationParams):
    request_id: RequestId | None = None
    """The ID of the request to cancel; MUST match a request previously issued in the same direction.

    Required on the wire through 2025-06-18; optional at 2025-11-25; required again from
    2026-07-28, where it must name a request the client issued (servers send this only
    to terminate a `subscriptions/listen` stream).
    """
    reason: str | None = None
    """An optional string describing the reason for the cancellation."""


class CancelledNotification(Notification[CancelledNotificationParams, Literal["notifications/cancelled"]]):
    """Sent by either side to cancel a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency it MAY
    arrive after the request has already finished. A client MUST NOT attempt to
    cancel its `initialize` request.
    """

    method: Literal["notifications/cancelled"] = "notifications/cancelled"
    params: CancelledNotificationParams


class ElicitCompleteNotificationParams(NotificationParams):
    """Parameters for elicitation completion notifications."""

    elicitation_id: str
    """The unique identifier of the elicitation that was completed."""


class ElicitCompleteNotification(
    Notification[ElicitCompleteNotificationParams, Literal["notifications/elicitation/complete"]]
):
    """Server notification that a URL mode elicitation has been completed.

    Clients MAY use it to retry requests that received a URLElicitationRequiredError
    or update the UI; delivery is not guaranteed, so clients must not wait
    indefinitely. New in protocol 2025-11-25 with URL mode itself.
    """

    method: Literal["notifications/elicitation/complete"] = "notifications/elicitation/complete"
    params: ElicitCompleteNotificationParams


# Kept as a raw JSON Schema dict so callers can hand it straight to a validator;
# the per-version packages model RequestedSchema/PrimitiveSchemaDefinition strictly.
ElicitRequestedSchema: TypeAlias = dict[str, Any]


class ElicitRequestFormParams(RequestParams):
    """Parameters for form mode elicitation requests.

    Form mode collects non-sensitive information from the user via an in-band form
    rendered by the client.
    """

    mode: Literal["form"] = "form"
    """The elicitation mode (always "form" for this type)."""

    message: str
    """The message to present to the user describing what information is being requested."""

    requested_schema: ElicitRequestedSchema
    """Restricted JSON Schema subset for the expected response: top-level properties only, no nesting."""

    task: TaskMetadata | None = None
    """If specified, the caller requests task-augmented execution (2025-11-25 only)."""


class ElicitRequestURLParams(RequestParams):
    """Parameters for URL mode elicitation requests.

    URL mode directs users to external URLs for sensitive out-of-band interactions
    like OAuth flows, credential collection, or payment processing. New in 2025-11-25.
    """

    mode: Literal["url"] = "url"
    """The elicitation mode (always "url" for this type)."""

    message: str
    """The message to present to the user explaining why the interaction is needed."""

    url: str
    """The URL that the user should navigate to."""

    elicitation_id: str | None = None
    """Server-unique elicitation ID; the client MUST treat it as opaque.
    Required on the wire at 2025-11-25; removed at 2026-07-28."""

    task: TaskMetadata | None = None
    """If specified, the caller requests task-augmented execution (2025-11-25 only)."""


ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams
"""Parameters for elicitation requests - either form or URL mode."""


class ElicitRequest(Request[ElicitRequestParams, Literal["elicitation/create"]]):
    """A request from the server to elicit additional information from the user via the client."""

    method: Literal["elicitation/create"] = "elicitation/create"
    params: ElicitRequestParams


class ElicitResult(Result):
    """The client's response to an elicitation request."""

    action: Literal["accept", "decline", "cancel"]
    """The user action: "accept" = submitted the form / confirmed (or consented to URL
    navigation); "decline" = explicitly declined; "cancel" = dismissed without an
    explicit choice."""

    content: dict[str, str | int | float | bool | list[str] | None] | None = None
    """Submitted form data matching the requested schema; present only when action
    is "accept" in form mode (omitted for URL mode)."""


class ElicitationRequiredErrorData(MCPModel):
    """Error data for the -32042 URL-elicitation-required error: the request cannot
    proceed until the listed URL mode elicitations are completed.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    elicitations: list[ElicitRequestURLParams]
    """List of URL mode elicitations that must be completed."""


InputRequest: TypeAlias = CreateMessageRequest | ListRootsRequest | ElicitRequest
"""A single server-initiated input request embedded in `InputRequiredResult` (2026-07-28).

Discriminated by `method`. On 2026-07-28 these embedded payloads take the place
of standalone server-to-client JSON-RPC requests.
"""

InputRequests: TypeAlias = dict[str, InputRequest]
"""A map of server-initiated requests that the client must fulfill (2026-07-28).

Keys are server-assigned identifiers. Carried by `InputRequiredResult.input_requests`
and by the tasks extension.
"""

InputResponse: TypeAlias = CreateMessageResult | CreateMessageResultWithTools | ListRootsResult | ElicitResult
"""A client response to a single server-initiated input request (2026-07-28).

`CreateMessageResultWithTools` is this SDK's array-content split of the schema's
single `CreateMessageResult` arm; the wire union has three arms.
"""

InputResponses: TypeAlias = dict[str, InputResponse]
"""A map of client responses to server-initiated input requests (2026-07-28).

Keys match those of the `InputRequests` map the server sent. Also used by the
tasks extension's `tasks/update` params.
"""


class InputRequiredResult(Result):
    """The server needs additional input before the original request can complete (2026-07-28).

    Returned in place of the normal result of an interactive client request
    (`tools/call`, `prompts/get`, `resources/read`). The client fulfills
    `input_requests` and retries the original request, carrying the responses
    and the echoed `request_state`. At least one of those two fields is
    present on the wire (spec MUST).
    """

    result_type: Literal["input_required"] = "input_required"
    """Discriminating tag for the dual-result response unions."""

    input_requests: InputRequests | None = None
    """Requests the client must complete before retrying. Keys are server-assigned."""

    request_state: str | None = None
    """Opaque state to pass back verbatim when the client retries the original request."""

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if not self.input_requests and self.request_state is None:
            raise ValueError("InputRequiredResult requires at least one of input_requests or request_state")
        return self


# Forward refs to InputResponses; rebuild at import time rather than first use.
InputResponseRequestParams.model_rebuild()
ReadResourceRequestParams.model_rebuild()
GetPromptRequestParams.model_rebuild()
CallToolRequestParams.model_rebuild()

# Top-level message unions: superset across all supported protocol versions.
# Per-version validity is recorded in `mcp_types.methods`, not enforced here.

ClientRequest = (
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
    | DiscoverRequest
    | SubscriptionsListenRequest
)
"""Union of client-to-server request payloads across all supported protocol versions.

The 2025-11-25 task requests are deliberately excluded (types-only).
"""

client_request_adapter = TypeAdapter[ClientRequest](ClientRequest)


ClientNotification = (
    CancelledNotification | ProgressNotification | InitializedNotification | RootsListChangedNotification
)
"""Notifications sent from the client to the server.

`TaskStatusNotification` is deliberately excluded (types-only).
"""

client_notification_adapter = TypeAdapter[ClientNotification](ClientNotification)


ClientResult = EmptyResult | CreateMessageResult | CreateMessageResultWithTools | ListRootsResult | ElicitResult
client_result_adapter = TypeAdapter[ClientResult](ClientResult)


ServerRequest = PingRequest | CreateMessageRequest | ListRootsRequest | ElicitRequest
"""Union of standalone JSON-RPC requests a server can send to a client.

Live through 2025-11-25 only: 2026-07-28 has no server-to-client JSON-RPC
requests (these payloads are embedded in `InputRequiredResult` instead).
"""

server_request_adapter = TypeAdapter[ServerRequest](ServerRequest)


ServerNotification = (
    CancelledNotification
    | ProgressNotification
    | LoggingMessageNotification
    | ResourceUpdatedNotification
    | ResourceListChangedNotification
    | ToolListChangedNotification
    | PromptListChangedNotification
    | ElicitCompleteNotification
    | SubscriptionsAcknowledgedNotification
)
"""Union of server-to-client notification payloads across all supported protocol versions.

`TaskStatusNotification` is deliberately excluded (types-only).
"""

server_notification_adapter = TypeAdapter[ServerNotification](ServerNotification)


ServerResult = (
    EmptyResult
    | InitializeResult
    | DiscoverResult
    | CompleteResult
    | GetPromptResult
    | ListPromptsResult
    | ListResourcesResult
    | ListResourceTemplatesResult
    | ReadResourceResult
    | CallToolResult
    | ListToolsResult
    | SubscriptionsListenResult
    | InputRequiredResult
)
"""Union of every result payload a server can return for a client request.

`InputRequiredResult` is deliberately last: both of its fields are optional,
so an earlier position would shadow other members during union resolution.
"""
server_result_adapter = TypeAdapter[ServerResult](ServerResult)
