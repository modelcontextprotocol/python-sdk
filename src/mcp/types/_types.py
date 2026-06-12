"""MCP protocol types: one model set spanning every supported protocol version.

The models are a superset across protocol revisions: each class carries every
field any supported revision defines, and a field one revision requires on the
wire may still be optional here because other revisions lack it entirely.
Docstrings state the per-version wire facts; version-specific emission and
parsing live in ``mcp.types.wire``, not here.

Comments of the form ``# OD-<n> alternative: <one clause>`` (and ``# M-<n>``
in ``mcp.types.jsonrpc``) mark reviewed design decisions at the spot where
they bite: each names the design alternative that was considered and NOT
implemented — the code as written is the accepted choice. The comment text is
the complete statement of the alternative; the id is just a stable label for
referring to the decision in review discussion. They are records, not TODOs.
"""

from __future__ import annotations

from typing import Annotated, Any, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, FileUrl, TypeAdapter
from pydantic.alias_generators import to_camel
from typing_extensions import NotRequired, TypedDict

from mcp.types.jsonrpc import RequestId

LATEST_PROTOCOL_VERSION = "2025-11-25"
"""The latest released version of the Model Context Protocol.

The 2026-07-28 revision also modeled in this package is unreleased: its
schema is published but still subject to change, so it is deliberately newer
than this constant and absent from
`mcp.shared.version.SUPPORTED_PROTOCOL_VERSIONS`. Both move when the
specification releases it.

You can find the latest specification at https://modelcontextprotocol.io/specification/latest.
"""

DEFAULT_NEGOTIATED_VERSION = "2025-03-26"
"""The default negotiated version of the Model Context Protocol when no version is specified.

We need this to satisfy the MCP specification, which requires the server to assume a specific version if none is
provided by the client.

See the "Protocol Version Header" at
https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#protocol-version-header.
"""

ProgressToken = str | int
Role = Literal["user", "assistant"]

IconTheme = Literal["light", "dark"]
"""Theme an icon is designed for. Wire values of ``Icon.theme`` (2025-11-25+)."""


class MCPModel(BaseModel):
    """Base class for all MCP protocol types."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Meta: TypeAlias = dict[str, Any]


PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
"""Reserved request `_meta` key: the MCP protocol version for this request (2026-07-28).

2026-07-28 requires the client to send it on every request. For the HTTP
transport its value must match the `MCP-Protocol-Version` header.
"""

CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
"""Reserved request `_meta` key: the client `Implementation` making the request (2026-07-28).

2026-07-28 requires the client to send it on every request; with the
initialize handshake removed there, this key replaces the handshake's
`clientInfo`.
"""

CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
"""Reserved request `_meta` key: the client's per-request `ClientCapabilities` (2026-07-28).

2026-07-28 requires the client to send it on every request; servers must not
infer capabilities from prior requests.
"""

LOG_LEVEL_META_KEY = "io.modelcontextprotocol/logLevel"
"""Reserved request `_meta` key: the desired log level for this request (2026-07-28).

Replaces the former `logging/setLevel` RPC. Deprecated as of protocol version
2026-07-28 (SEP-2577); if absent, the server must not send log notifications
for this request.
"""


class RequestParamsMeta(TypedDict, extra_items=Any):
    """The `_meta` object on request params (schema name: `RequestMetaObject`).

    An open map: arbitrary `_meta` keys — including the reserved
    `io.modelcontextprotocol/*` keys — are preserved on round-trip via
    ``extra_items=Any``. The reserved keys carry the per-request state that
    2026-07-28 moved into `_meta` (protocol version, client info, client
    capabilities, log level); read or set them via the ``*_META_KEY``
    constants.
    """

    # Deliberately no explicit alias: a TypedDict carries no pydantic config of
    # its own, so pydantic validates and serializes it with the configuration
    # of the model field embedding it (`RequestParams.meta`). That model
    # config's `alias_generator=to_camel` is what maps this key to
    # "progressToken" on the wire, in both directions.
    progress_token: NotRequired[ProgressToken]
    """
    If specified, the caller requests out-of-band progress notifications for
    this request (as represented by notifications/progress). The value of this
    parameter is an opaque token that will be attached to any subsequent
    notifications. The receiver is not obligated to provide these notifications.
    """


class RequestParams(MCPModel):
    meta: RequestParamsMeta | None = Field(alias="_meta", default=None)


class PaginatedRequestParams(RequestParams):
    """Common params for paginated requests."""

    cursor: str | None = None
    """An opaque token representing the current pagination position.

    If provided, the server should return results starting after this cursor.
    """


class NotificationParams(MCPModel):
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


RequestParamsT = TypeVar("RequestParamsT", bound=RequestParams | dict[str, Any] | None)
NotificationParamsT = TypeVar("NotificationParamsT", bound=NotificationParams | dict[str, Any] | None)
MethodT = TypeVar("MethodT", bound=str)


class Request(MCPModel, Generic[RequestParamsT, MethodT]):
    """Base class for JSON-RPC requests."""

    method: MethodT
    params: RequestParamsT


class PaginatedRequest(Request[PaginatedRequestParams | None, MethodT], Generic[MethodT]):
    """Base class for paginated requests, matching the schema's PaginatedRequest interface."""

    params: PaginatedRequestParams | None = None
    """Pagination params.

    Optional on 2025-11-25 and older wires; required on the 2026-07-28 wire,
    where every request must carry `params._meta` with the reserved keys.
    """


class Notification(MCPModel, Generic[NotificationParamsT, MethodT]):
    """Base class for JSON-RPC notifications."""

    method: MethodT
    params: NotificationParamsT


ResultType = Literal["complete", "input_required"] | str
"""Indicates the type of a Result object, allowing the client to determine how to parse it.

- "complete": the request completed successfully and the result contains the final content.
- "input_required": the request requires additional input; the result contains an
  InputRequiredResult with instructions for the client to provide additional input
  before retrying the original request.

Introduced in protocol 2026-07-28. The union is open: values outside the two named
literals are reserved for future protocol versions and extensions (the tasks extension
reserves "task"). Pre-2026-07-28 peers never send the carrying field; the spec defines
an absent `resultType` as equivalent to "complete".
"""


class Result(MCPModel):
    """Base class for JSON-RPC results."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """

    result_type: ResultType | None = None
    """Discriminates complete results from input-required results (2026-07-28).

    `None` means the field was absent on the wire (pre-2026-07-28 peers never
    send it), which the spec defines as equivalent to "complete". The
    2026-07-28 wire requires the field on every result.
    """


class PaginatedResult(Result):
    """Base class for results of paginated list operations.

    Matches the schema's PaginatedResult interface; concrete list results
    (ListToolsResult, ListResourcesResult, ListResourceTemplatesResult,
    ListPromptsResult) subclass it.
    """

    next_cursor: str | None = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """


class CacheableResult(Result):
    """Base class for results that carry client-side caching directives (2026-07-28).

    The 2026-07-28 wire requires both fields; 2025-11-25 and earlier revisions
    do not define them, so both are optional here.
    """

    ttl_ms: int | None = None
    """How long, in milliseconds, the client MAY cache this response before
    re-fetching — analogous to HTTP Cache-Control max-age.

    0 means the response SHOULD be considered immediately stale; a positive value
    means the client SHOULD consider the result fresh for that many milliseconds.
    Must be non-negative. `None` means unset.
    """

    cache_scope: Literal["public", "private"] | None = None
    """Intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    With "public", any client or intermediary (e.g. a shared gateway or proxy)
    MAY cache the response and serve it to any user; with "private", only the
    requesting user's client MAY cache it, and shared caches MUST NOT serve a
    cached copy to a different user. `None` means unset.
    """


class EmptyResult(Result):
    """A result that indicates success but carries no data."""


class BaseMetadata(MCPModel):
    """Base class for entities with a programmatic name and an optional display title."""

    name: str
    """Intended for programmatic or logical use, but used as a display name in past
    specs or fallback (if title isn't present)."""

    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class Icon(MCPModel):
    """An optionally-sized icon that can be displayed in a user interface.

    Added in protocol 2025-11-25; carried in the optional ``icons`` array of
    tools, resources, resource templates, prompts, and implementations. Never
    present on the wire in earlier protocol versions.
    """

    src: str
    """A standard URI pointing to an icon resource.

    May be an HTTP/HTTPS URL or a ``data:`` URI with Base64-encoded image data.

    Consumers SHOULD take steps to ensure URLs serving icons are from the same
    domain as the client/server or a trusted domain, and SHOULD take
    appropriate precautions when consuming SVGs, as they can contain
    executable JavaScript.
    """

    mime_type: str | None = None
    """Optional MIME type override if the source MIME type is missing or generic.

    For example: ``"image/png"``, ``"image/jpeg"``, or ``"image/svg+xml"``.
    """

    sizes: list[str] | None = None
    """Optional array of strings specifying sizes at which the icon can be used.

    Each string should be in WxH format (e.g., ``"48x48"``, ``"96x96"``) or
    ``"any"`` for scalable formats like SVG. If not provided, the client
    should assume the icon can be used at any size.
    """

    theme: IconTheme | None = None
    """Optional specifier for the theme this icon is designed for.

    ``"light"`` indicates the icon is designed to be used with a light
    background, and ``"dark"`` indicates the icon is designed to be used with
    a dark background. If not provided, the client should assume the icon can
    be used with any theme.
    """


class Implementation(BaseMetadata):
    """Describes the name and version of an MCP implementation."""

    version: str

    title: str | None = None
    """An optional human-readable title for this implementation."""

    description: str | None = None
    """An optional human-readable description of what this implementation does."""

    website_url: str | None = None
    """An optional URL of the website for this implementation."""

    icons: list[Icon] | None = None
    """An optional list of icons for this implementation."""


class RootsCapability(MCPModel):
    """Capability for root operations.

    Deprecated as a whole in protocol 2026-07-28 (SEP-2577) but remains in the
    specification's deprecated-features registry; used on all earlier-version
    sessions.
    """

    list_changed: bool | None = None
    """Whether the client supports notifications for changes to the roots list.

    Removed in protocol 2026-07-28 (the 2026-07-28 `roots` capability is an
    empty object); meaningful on 2025-11-25 and earlier sessions.
    """


class SamplingContextCapability(MCPModel):
    """Capability for context inclusion during sampling.

    Indicates support for non-'none' values in the includeContext parameter.
    SOFT-DEPRECATED: New implementations should use tools parameter instead.
    """


class SamplingToolsCapability(MCPModel):
    """Capability indicating support for tool calling during sampling.

    When present in ClientCapabilities.sampling, indicates that the client
    supports the tools and toolChoice parameters in sampling requests.
    """


class FormElicitationCapability(MCPModel):
    """Capability for form mode elicitation."""


class UrlElicitationCapability(MCPModel):
    """Capability for URL mode elicitation."""


class ElicitationCapability(MCPModel):
    """Capability for elicitation operations.

    Clients must support at least one mode (form or url).
    """

    form: FormElicitationCapability | None = None
    """Present if the client supports form mode elicitation."""

    url: UrlElicitationCapability | None = None
    """Present if the client supports URL mode elicitation."""


class SamplingCapability(MCPModel):
    """Sampling capability structure, allowing fine-grained capability advertisement."""

    context: SamplingContextCapability | None = None
    """
    Present if the client supports non-'none' values for includeContext parameter.
    SOFT-DEPRECATED: New implementations should use tools parameter instead.
    """
    tools: SamplingToolsCapability | None = None
    """
    Present if the client supports tools and toolChoice parameters in sampling requests.
    Presence indicates full tool calling support during sampling.
    """


class TasksListCapability(MCPModel):
    """Capability for tasks listing operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TasksCancelCapability(MCPModel):
    """Capability for tasks cancel operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TasksCreateMessageCapability(MCPModel):
    """Capability for task-augmented sampling/createMessage requests.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TasksSamplingCapability(MCPModel):
    """Capability for task-augmented sampling operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    create_message: TasksCreateMessageCapability | None = None
    """Whether the client supports task-augmented sampling/createMessage."""


class TasksCreateElicitationCapability(MCPModel):
    """Capability for task-augmented elicitation/create requests.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TasksElicitationCapability(MCPModel):
    """Capability for task-augmented elicitation operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    create: TasksCreateElicitationCapability | None = None
    """Whether the client supports task-augmented elicitation/create."""


class ClientTasksRequestsCapability(MCPModel):
    """Specifies which request types the client can augment with tasks.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    sampling: TasksSamplingCapability | None = None
    """Task support for sampling requests."""

    elicitation: TasksElicitationCapability | None = None
    """Task support for elicitation requests."""


class ClientTasksCapability(MCPModel):
    """Capability for client tasks operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    list: TasksListCapability | None = None
    """Whether this client supports tasks/list."""

    cancel: TasksCancelCapability | None = None
    """Whether this client supports tasks/cancel."""

    requests: ClientTasksRequestsCapability | None = None
    """Specifies which request types can be augmented with tasks."""


class ClientCapabilities(MCPModel):
    """Capabilities a client may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the client supports."""
    sampling: SamplingCapability | None = None
    """
    Present if the client supports sampling from an LLM.
    Can contain fine-grained capabilities like context and tools support.
    """
    elicitation: ElicitationCapability | None = None
    """Present if the client supports elicitation from the user."""
    roots: RootsCapability | None = None
    """Present if the client supports listing roots."""
    extensions: dict[str, dict[str, Any]] | None = None
    """Optional MCP extensions that the client supports (2026-07-28).

    Keys are extension identifiers (e.g. "io.modelcontextprotocol/oauth-client-credentials"),
    values are per-extension settings objects; an empty object indicates support
    with no settings.
    """
    tasks: ClientTasksCapability | None = None
    """Present if the client supports task-augmented requests (2025-11-25 only)."""


class UnsupportedProtocolVersionErrorData(MCPModel):
    """Error data for the -32004 unsupported-protocol-version error (2026-07-28).

    Servers return this when a request claims a protocol version they do not
    support. The client should choose a mutually supported version from
    ``supported`` and retry the request.
    """

    supported: list[str]
    """Protocol versions the server supports.

    The client should choose a mutually supported version from this list and retry.
    """

    requested: str
    """The protocol version that was requested by the client."""


class MissingRequiredClientCapabilityErrorData(MCPModel):
    """Error data for the 2026-07-28 MissingRequiredClientCapabilityError (-32003).

    Servers return this when processing a request requires a capability the
    client did not declare in the request's `clientCapabilities`. The client
    should re-send the request declaring the listed capabilities (or fail).
    """

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
    """Capability for task-augmented tools/call requests.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TasksToolsCapability(MCPModel):
    """Capability for task-augmented tool operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    call: TasksCallCapability | None = None
    """Whether the server supports task-augmented tools/call."""


class ServerTasksRequestsCapability(MCPModel):
    """Specifies which request types the server can augment with tasks.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    tools: TasksToolsCapability | None = None
    """Task support for tool requests."""


class ServerTasksCapability(MCPModel):
    """Capability for server tasks operations.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    list: TasksListCapability | None = None
    """Whether this server supports tasks/list."""

    cancel: TasksCancelCapability | None = None
    """Whether this server supports tasks/cancel."""

    requests: ServerTasksRequestsCapability | None = None
    """Specifies which request types can be augmented with tasks."""


class ServerCapabilities(MCPModel):
    """Capabilities that a server may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the server supports."""

    logging: LoggingCapability | None = None
    """Present if the server supports sending log messages to the client."""

    prompts: PromptsCapability | None = None
    """Present if the server offers any prompt templates."""

    resources: ResourcesCapability | None = None
    """Present if the server offers any resources to read."""

    tools: ToolsCapability | None = None
    """Present if the server offers any tools to call."""

    completions: CompletionsCapability | None = None
    """Present if the server offers autocompletion suggestions for prompts and resources."""

    extensions: dict[str, dict[str, Any]] | None = None
    """Optional MCP extensions that the server supports (2026-07-28).

    Keys are extension identifiers (e.g. "io.modelcontextprotocol/tasks");
    values are per-extension settings objects. An empty object indicates
    support with no settings.
    """

    tasks: ServerTasksCapability | None = None
    """Present if the server supports task-augmented requests (2025-11-25 only)."""


# Lifecycle handshake (removed in protocol 2026-07-28).
#
# Protocol 2026-07-28 removed the initialize handshake and ping in favor of
# `server/discover` plus per-request `_meta`. The handshake types stay defined
# because earlier-version sessions still use them; every type the 2026-07-28
# revision removed — here and elsewhere in this module — carries the same
# "Removed in protocol 2026-07-28" docstring line.
# OD-2 alternative: move removed types to a `mcp.types.legacy` module behind PEP 562 aliases.


class InitializeRequestParams(RequestParams):
    """Parameters for the initialize request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    protocol_version: str
    """The latest version of the Model Context Protocol that the client supports."""
    capabilities: ClientCapabilities
    client_info: Implementation


class InitializeRequest(Request[InitializeRequestParams, Literal["initialize"]]):
    """This request is sent from the client to the server when it first connects, asking it
    to begin initialization.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    The `server/discover` flow plus per-request `_meta` replace the handshake there.
    """

    method: Literal["initialize"] = "initialize"
    params: InitializeRequestParams


class InitializeResult(Result):
    """After receiving an initialize request from the client, the server sends this.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    The 2026-07-28 revision replaces the initialize handshake with `server/discover`
    (see `DiscoverResult`).
    """

    protocol_version: str
    """The version of the Model Context Protocol that the server wants to use."""
    capabilities: ServerCapabilities
    server_info: Implementation
    instructions: str | None = None
    """Instructions describing how to use the server and its features."""


class InitializedNotification(Notification[NotificationParams | None, Literal["notifications/initialized"]]):
    """This notification is sent from the client to the server after initialization has
    finished.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["notifications/initialized"] = "notifications/initialized"
    params: NotificationParams | None = None


class PingRequest(Request[RequestParams | None, Literal["ping"]]):
    """A ping, issued by either the server or the client, to check that the other party is
    still alive.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["ping"] = "ping"
    params: RequestParams | None = None


class DiscoverRequest(Request[RequestParams | None, Literal["server/discover"]]):
    """A request from the client asking the server to advertise its supported
    protocol versions, capabilities, and other metadata (2026-07-28 only).

    Servers speaking 2026-07-28 MUST implement ``server/discover``; clients MAY
    call it but are not required to - version negotiation can also happen
    inline via per-request ``_meta``.
    """

    method: Literal["server/discover"] = "server/discover"
    params: RequestParams | None = None
    """Required on the 2026-07-28 wire, where its ``_meta`` must carry the
    reserved ``io.modelcontextprotocol/*`` keys; optional here like every
    other wire-required 2026-07-28 field (see the module docstring).
    """


class DiscoverResult(CacheableResult):
    """The result returned by the server for a `server/discover` request (2026-07-28)."""

    supported_versions: list[str]
    """MCP protocol versions this server supports.

    The client should choose a version from this list for use in subsequent requests.
    """

    capabilities: ServerCapabilities
    """The capabilities of the server."""

    server_info: Implementation
    """Information about the server software implementation."""

    instructions: str | None = None
    """Natural-language guidance describing the server and its features.

    This can be used by clients to improve an LLM's understanding of available
    tools (e.g., by including it in a system prompt). It should focus on
    information that helps the model use the server effectively and should not
    duplicate information already in tool descriptions.
    """


# Tasks (removed in protocol 2026-07-28).
#
# Protocol 2025-11-25 introduced task-augmented requests; protocol 2026-07-28
# removed them from the core specification (tasks continue as a protocol
# extension). The 2025-11-25 task types are defined here types-only: none of
# their methods appear in the request/notification unions below or in the
# per-version method tables, so they are never dispatched.
# OD-3 alternative: a `mcp/extensions/tasks/` package carrying the extension's task types attaches here.


class ToolExecution(MCPModel):
    """Execution-related properties for a tool.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (introduced with the experimental core tasks support; the
    tasks extension has no per-tool execution declaration).
    """

    task_support: Literal["forbidden", "optional", "required"] | None = None
    """
    Indicates whether this tool supports task-augmented execution.
    This allows clients to handle long-running operations through polling
    the task system.

    - "forbidden": Tool does not support task-augmented execution (default when absent)
    - "optional": Tool may support task-augmented execution
    - "required": Tool requires task-augmented execution

    Default: "forbidden"
    """


class TaskMetadata(MCPModel):
    """Metadata for augmenting a request with task execution.

    Include this in the `task` field of the request parameters.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (the tasks extension has no request-side task-creation
    metadata).
    """

    ttl: int | None = None
    """Requested duration in milliseconds to retain task from creation."""


class RelatedTaskMetadata(MCPModel):
    """Metadata for associating messages with a task.

    Include this in the ``_meta`` field under the key
    ``io.modelcontextprotocol/related-task``.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    task_id: str
    """The task identifier this message is associated with."""


TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]
"""The status of a task.

Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
"""


class Task(MCPModel):
    """Data associated with a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    task_id: str
    """The task identifier."""

    status: TaskStatus
    """Current task state."""

    status_message: str | None = None
    """Optional human-readable message describing the current task state.

    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """

    created_at: str
    """ISO 8601 timestamp when the task was created."""

    last_updated_at: str
    """ISO 8601 timestamp when the task was last updated."""

    ttl: int | None
    """Actual retention duration from creation in milliseconds, null for unlimited."""

    poll_interval: int | None = None
    """Suggested polling interval in milliseconds."""


class CreateTaskResult(Result):
    """A response to a task-augmented request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    task: Task


class GetTaskRequestParams(RequestParams):
    """Parameters for a tasks/get request."""

    task_id: str
    """The task identifier to query."""


class GetTaskRequest(Request[GetTaskRequestParams, Literal["tasks/get"]]):
    """A request to retrieve the state of a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


class GetTaskResult(Result, Task):
    """The response to a tasks/get request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class CancelTaskRequestParams(RequestParams):
    """Parameters for a tasks/cancel request."""

    task_id: str
    """The task identifier to cancel."""


class CancelTaskRequest(Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    """A request to cancel a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class CancelTaskResult(Result, Task):
    """The response to a tasks/cancel request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class TaskStatusNotificationParams(NotificationParams, Task):
    """Parameters for a `notifications/tasks/status` notification."""


class TaskStatusNotification(Notification[TaskStatusNotificationParams, Literal["notifications/tasks/status"]]):
    """An optional notification from the receiver to the requestor, informing them that a
    task's status has changed. Receivers are not required to send these notifications.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    method: Literal["notifications/tasks/status"] = "notifications/tasks/status"
    params: TaskStatusNotificationParams


class GetTaskPayloadRequestParams(RequestParams):
    """Parameters for a tasks/result request."""

    task_id: str
    """The task identifier to retrieve results for."""


class GetTaskPayloadRequest(Request[GetTaskPayloadRequestParams, Literal["tasks/result"]]):
    """A request to retrieve the result of a completed task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (the tasks extension delivers terminal payloads inline in
    tasks/get responses instead).
    """

    method: Literal["tasks/result"] = "tasks/result"
    params: GetTaskPayloadRequestParams


class GetTaskPayloadResult(Result):
    """The response to a tasks/result request.

    The structure matches the result type of the original request; for example, a
    tools/call task would return the CallToolResult structure. The payload arrives
    as extra wire fields on this open object, which the SDK's default extra-field
    policy does not retain: validating a tasks/result response into this class
    keeps only ``_meta``. Callers that know the original request should validate
    the response into that request's result type (e.g. ``CallToolResult``)
    instead, and custom server handlers should return the original request's
    result object directly rather than wrapping it in this class.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """


class ListTasksRequest(PaginatedRequest[Literal["tasks/list"]]):
    """A request to retrieve a list of tasks.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (the tasks extension deliberately drops tasks/list).
    """

    method: Literal["tasks/list"] = "tasks/list"


class ListTasksResult(PaginatedResult):
    """The response to a tasks/list request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    tasks: list[Task]
    """The list of tasks."""


class ProgressNotificationParams(NotificationParams):
    """Parameters for progress notifications."""

    progress_token: ProgressToken
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
    message: str | None = None
    """Message related to progress.

    This should provide relevant human-readable progress information.
    """


class ProgressNotification(Notification[ProgressNotificationParams, Literal["notifications/progress"]]):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    method: Literal["notifications/progress"] = "notifications/progress"
    params: ProgressNotificationParams


class ListResourcesRequest(PaginatedRequest[Literal["resources/list"]]):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"] = "resources/list"


class Annotations(MCPModel):
    audience: list[Role] | None = None
    priority: Annotated[float, Field(ge=0.0, le=1.0)] | None = None


class Resource(BaseMetadata):
    """A known resource that the server is capable of reading."""

    uri: str
    """The URI of this resource."""

    description: str | None = None
    """A description of what this resource represents."""

    mime_type: str | None = None
    """The MIME type of this resource, if known."""

    size: int | None = None
    """The size of the raw resource content, in bytes (i.e., before base64 encoding or any tokenization), if known.

    This can be used by Hosts to display file sizes and estimate context window usage.
    """

    icons: list[Icon] | None = None
    """An optional list of icons for this resource."""

    annotations: Annotations | None = None

    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ResourceTemplate(BaseMetadata):
    """A template description for resources available on the server."""

    uri_template: str
    """A URI template (according to RFC 6570) that can be used to construct resource URIs."""

    description: str | None = None
    """A human-readable description of what this template is for."""

    mime_type: str | None = None
    """The MIME type for all resources that match this template.

    This should only be included if all resources matching this template have the same type.
    """

    icons: list[Icon] | None = None
    """An optional list of icons for this resource template."""

    annotations: Annotations | None = None

    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ListResourcesResult(PaginatedResult, CacheableResult):
    """The server's response to a resources/list request from the client."""

    resources: list[Resource]
    """The list of resources the server offers."""


class ListResourceTemplatesRequest(PaginatedRequest[Literal["resources/templates/list"]]):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"] = "resources/templates/list"


class ListResourceTemplatesResult(PaginatedResult, CacheableResult):
    """The server's response to a resources/templates/list request from the client."""

    resource_templates: list[ResourceTemplate]
    """The list of resource templates the server offers."""


class InputResponseRequestParams(RequestParams):
    """Base params for client requests that can carry responses to a server's
    input requests (2026-07-28 multi-round-trip flow).

    When a request previously returned an InputRequiredResult, the client
    retries the original request with these fields populated. Extended by
    CallToolRequestParams, GetPromptRequestParams and ReadResourceRequestParams.
    """

    input_responses: InputResponses | None = None
    """Responses to the server's input requests from the InputRequiredResult.

    For each key in the InputRequiredResult's inputRequests map, the same key
    must appear here with the client's result for that request.
    """
    request_state: str | None = None
    """Opaque request state from the InputRequiredResult, passed back to the
    server verbatim when the client retries the original request."""


class ReadResourceRequestParams(InputResponseRequestParams):
    """Parameters for reading a resource."""

    uri: str
    """
    The URI of the resource to read. The URI can use any protocol; it is up to the
    server how to interpret it.
    """


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
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


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


class ReadResourceResult(CacheableResult):
    """The server's response to a resources/read request from the client."""

    contents: list[TextResourceContents | BlobResourceContents]
    """The contents of the resource or sub-resources that were read."""


class ResourceListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/resources/list_changed"]]
):
    """An optional notification from the server to the client, informing it that the list
    of resources it can read from has changed.
    """

    method: Literal["notifications/resources/list_changed"] = "notifications/resources/list_changed"
    params: NotificationParams | None = None


class SubscribeRequestParams(RequestParams):
    """Parameters for subscribing to a resource.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    uri: str
    """
    The URI of the resource to subscribe to. The URI can use any protocol; it is up to
    the server how to interpret it.
    """


class SubscribeRequest(Request[SubscribeRequestParams, Literal["resources/subscribe"]]):
    """Sent from the client to request resources/updated notifications from the server
    whenever a particular resource changes.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    2026-07-28 sessions replace per-URI subscribe with ``subscriptions/listen``
    (``SubscriptionsListenRequest``).
    """

    method: Literal["resources/subscribe"] = "resources/subscribe"
    params: SubscribeRequestParams


class UnsubscribeRequestParams(RequestParams):
    """Parameters for unsubscribing from a resource.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    uri: str
    """The URI of the resource to unsubscribe from."""


class UnsubscribeRequest(Request[UnsubscribeRequestParams, Literal["resources/unsubscribe"]]):
    """Sent from the client to request cancellation of resources/updated notifications from
    the server.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    2026-07-28 peers manage resource subscriptions declaratively via subscriptions/listen
    (SubscriptionsListenRequest) instead.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    params: UnsubscribeRequestParams


class ResourceUpdatedNotificationParams(NotificationParams):
    """Parameters for resource update notifications."""

    uri: str
    """
    The URI of the resource that has been updated. This might be a sub-resource of the
    one that the client actually subscribed to.
    """


class ResourceUpdatedNotification(
    Notification[ResourceUpdatedNotificationParams, Literal["notifications/resources/updated"]]
):
    """A notification from the server to the client, informing it that a resource has
    changed and may need to be read again.
    """

    method: Literal["notifications/resources/updated"] = "notifications/resources/updated"
    params: ResourceUpdatedNotificationParams


class SubscriptionFilter(MCPModel):
    """The set of notification types a client may opt in to on a
    subscriptions/listen request (2026-07-28).

    Each notification type is opt-in; the server MUST NOT send notification
    types the client has not explicitly requested here. The same shape is
    echoed back by the server in notifications/subscriptions/acknowledged as
    the subset it agreed to honor.

    Extensions merge additional keys into this object on the wire (e.g. the
    tasks extension's ``taskIds``), so unknown keys are preserved on
    round-trip rather than ignored.
    """

    # OD-9 alternative: a codec-facing extra="allow" parse layer on all models instead of this single carve-out.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    tools_list_changed: bool | None = None
    """If true, receive notifications/tools/list_changed."""

    prompts_list_changed: bool | None = None
    """If true, receive notifications/prompts/list_changed."""

    resources_list_changed: bool | None = None
    """If true, receive notifications/resources/list_changed."""

    resource_subscriptions: list[str] | None = None
    """Subscribe to notifications/resources/updated for these resource URIs.

    Replaces the former resources/subscribe RPC.
    """


class SubscriptionsListenRequestParams(RequestParams):
    """Parameters for a subscriptions/listen request (2026-07-28)."""

    notifications: SubscriptionFilter
    """The notifications the client opts in to on this stream.

    The server MUST NOT send notification types the client has not explicitly
    requested.
    """


class SubscriptionsListenRequest(Request[SubscriptionsListenRequestParams, Literal["subscriptions/listen"]]):
    """Sent from the client to open a long-lived channel for receiving notifications
    outside the context of a specific request (2026-07-28).

    Replaces the previous HTTP GET endpoint and ensures consistent behavior between
    HTTP and STDIO.
    """

    method: Literal["subscriptions/listen"] = "subscriptions/listen"
    params: SubscriptionsListenRequestParams


class SubscriptionsAcknowledgedNotificationParams(NotificationParams):
    """Parameters for a notifications/subscriptions/acknowledged notification."""

    notifications: SubscriptionFilter
    """The subset of requested notification types the server agreed to honor.

    Only includes notification types the server actually supports; if the
    client requested an unsupported type (e.g., `promptsListChanged` when the
    server has no prompts), it is omitted from this set.
    """


class SubscriptionsAcknowledgedNotification(
    Notification[
        SubscriptionsAcknowledgedNotificationParams,
        Literal["notifications/subscriptions/acknowledged"],
    ]
):
    """Sent by the server as the first message on a subscriptions/listen stream
    to acknowledge that the subscription has been established and to report
    which notification types it agreed to honor (2026-07-28).
    """

    method: Literal["notifications/subscriptions/acknowledged"] = "notifications/subscriptions/acknowledged"
    params: SubscriptionsAcknowledgedNotificationParams


class ListPromptsRequest(PaginatedRequest[Literal["prompts/list"]]):
    """Sent from the client to request a list of prompts and prompt templates."""

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
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ListPromptsResult(PaginatedResult, CacheableResult):
    """The server's response to a prompts/list request from the client."""

    prompts: list[Prompt]
    """The list of prompts and prompt templates the server offers."""


class GetPromptRequestParams(InputResponseRequestParams):
    """Parameters for getting a prompt."""

    name: str
    """The name of the prompt or prompt template."""
    arguments: dict[str, str] | None = None
    """Arguments to use for templating the prompt."""


class GetPromptRequest(Request[GetPromptRequestParams, Literal["prompts/get"]]):
    """Used by the client to get a prompt provided by the server."""

    method: Literal["prompts/get"] = "prompts/get"
    params: GetPromptRequestParams


class TextContent(MCPModel):
    """Text content for a message."""

    type: Literal["text"] = "text"
    text: str
    """The text content of the message."""
    annotations: Annotations | None = None
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ImageContent(MCPModel):
    """Image content for a message."""

    type: Literal["image"] = "image"
    data: str
    """The base64-encoded image data."""
    mime_type: str
    """
    The MIME type of the image. Different providers may support different
    image types.
    """
    annotations: Annotations | None = None
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class AudioContent(MCPModel):
    """Audio content for a message."""

    type: Literal["audio"] = "audio"
    data: str
    """The base64-encoded audio data."""
    mime_type: str
    """
    The MIME type of the audio. Different providers may support different
    audio types.
    """
    annotations: Annotations | None = None
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ToolUseContent(MCPModel):
    """Content representing an assistant's request to invoke a tool.

    This content type appears in assistant messages when the LLM wants to call a
    tool during sampling-with-tools: in the content of a `sampling/createMessage`
    result, and in assistant-role messages replayed in subsequent
    `sampling/createMessage` requests. The server should execute the tool and
    return a ToolResultContent in the next user message.

    Available on 2025-11-25 and 2026-07-28 sessions only. Deprecated as of
    protocol 2026-07-28 (SEP-2577) but remains in the specification for at least
    twelve months and stays fully supported here.
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
    """Optional metadata about the tool use.

    Clients SHOULD preserve this field when including tool uses in subsequent
    sampling requests to enable caching optimizations.
    """


class ToolResultContent(MCPModel):
    """The result of a tool use, provided by the user back to the assistant.

    Appears in sampling messages (`sampling/createMessage`) as a response to a
    ToolUseContent block from the assistant; `tool_use_id` MUST match the `id` of
    that block. Requires the `sampling.tools` client capability (2025-11-25 and
    later). Deprecated as of protocol 2026-07-28 (SEP-2577) but remains valid on
    2026-07-28 sessions for at least twelve months.
    """

    type: Literal["tool_result"] = "tool_result"
    """Discriminator for tool result content."""

    tool_use_id: str
    """The ID of the tool use this result corresponds to.

    This MUST match the ID from a previous ToolUseContent.
    """

    content: list[ContentBlock] = []
    """The unstructured result content of the tool use.

    Same format as CallToolResult.content: text, images, audio, resource links,
    and embedded resources.
    """

    structured_content: Any = None
    """An optional structured result value.

    On 2026-07-28 sessions this can be any JSON value (object, array, string,
    number, boolean, or None); 2025-11-25 restricts it to a JSON object. If the
    tool defined an outputSchema, this SHOULD conform to that schema.
    """

    is_error: bool | None = None
    """Whether the tool use resulted in an error.

    If true, the content typically describes the error that occurred. Absent is
    equivalent to false.
    """

    meta: Meta | None = Field(alias="_meta", default=None)
    """Optional metadata about the tool result.

    Clients SHOULD preserve this field when including tool results in subsequent
    sampling requests to enable caching optimizations.
    """


SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent
"""Content block types allowed in sampling messages."""

SamplingContent: TypeAlias = TextContent | ImageContent | AudioContent
"""Basic content types for sampling responses (without tool use).

Used for backwards-compatible CreateMessageResult when tools are not used.
"""


class SamplingMessage(MCPModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """
    Message content. Can be a single content block or an array of content blocks
    for multi-modal messages and tool interactions.
    """
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """Returns the content as a list of content blocks, regardless of whether
        it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class EmbeddedResource(MCPModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    type: Literal["resource"] = "resource"
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ResourceLink(Resource):
    """A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    type: Literal["resource_link"] = "resource_link"


ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
"""A content block that can be used in prompts and tool results."""


class PromptMessage(MCPModel):
    """Describes a message returned as part of a prompt."""

    role: Role
    content: ContentBlock


class GetPromptResult(Result):
    """The server's response to a prompts/get request from the client."""

    description: str | None = None
    """An optional description for the prompt."""
    messages: list[PromptMessage]


class PromptListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/prompts/list_changed"]]
):
    """An optional notification from the server to the client, informing it that the list
    of prompts it offers has changed.
    """

    method: Literal["notifications/prompts/list_changed"] = "notifications/prompts/list_changed"
    params: NotificationParams | None = None


class ListToolsRequest(PaginatedRequest[Literal["tools/list"]]):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"] = "tools/list"


class ToolAnnotations(MCPModel):
    """Additional properties describing a Tool to clients.

    NOTE: all properties in ToolAnnotations are **hints**.
    They are not guaranteed to provide a faithful description of
    tool behavior (including descriptive properties like `title`).

    Clients should never make tool use decisions based on ToolAnnotations
    received from untrusted servers.
    """

    title: str | None = None
    """A human-readable title for the tool."""

    read_only_hint: bool | None = None
    """
    If true, the tool does not modify its environment.
    Default: false
    """

    destructive_hint: bool | None = None
    """
    If true, the tool may perform destructive updates to its environment.
    If false, the tool performs only additive updates.
    (This property is meaningful only when `read_only_hint == false`)
    Default: true
    """

    idempotent_hint: bool | None = None
    """
    If true, calling the tool repeatedly with the same arguments
    will have no additional effect on its environment.
    (This property is meaningful only when `read_only_hint == false`)
    Default: false
    """

    open_world_hint: bool | None = None
    """
    If true, this tool may interact with an "open world" of external
    entities. If false, the tool's domain of interaction is closed.
    For example, the world of a web search tool is open, whereas that
    of a memory tool is not.
    Default: true
    """


class Tool(BaseMetadata):
    """Definition for a tool the client can call."""

    description: str | None = None
    """A human-readable description of the tool."""
    input_schema: dict[str, Any]
    """A JSON Schema object defining the expected parameters for the tool."""
    execution: ToolExecution | None = None
    """Execution-related properties for this tool.

    2025-11-25 only; removed in protocol 2026-07-28 (tasks continue as an
    extension).
    """
    output_schema: dict[str, Any] | None = None
    """
    An optional JSON Schema object defining the structure of the tool's output
    returned in the structured_content field of a CallToolResult.
    """
    icons: list[Icon] | None = None
    """An optional list of icons for this tool."""
    annotations: ToolAnnotations | None = None
    """Optional additional tool information."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ListToolsResult(PaginatedResult, CacheableResult):
    """The server's response to a tools/list request from the client."""

    tools: list[Tool]
    """The list of tools the server offers."""


class CallToolRequestParams(InputResponseRequestParams):
    """Parameters for calling a tool."""

    name: str
    arguments: dict[str, Any] | None = None
    task: TaskMetadata | None = None
    """If specified, the caller is requesting task-augmented execution for this request.

    The request will return a CreateTaskResult immediately, and the actual result
    can be retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare
    support for task augmentation of specific request types in their capabilities.

    2025-11-25 only; removed in protocol 2026-07-28 (tasks continue as an extension).
    """


class CallToolRequest(Request[CallToolRequestParams, Literal["tools/call"]]):
    """Used by the client to invoke a tool provided by the server."""

    method: Literal["tools/call"] = "tools/call"
    params: CallToolRequestParams


class CallToolResult(Result):
    """The server's response to a tool call.

    Any errors that originate from the tool SHOULD be reported inside the result
    object, with `is_error` set to true, _not_ as an MCP protocol-level error
    response. Otherwise, the LLM would not be able to see that an error occurred
    and self-correct.

    However, any errors in _finding_ the tool, an error indicating that the
    server does not support tool calls, or any other exceptional conditions,
    should be reported as an MCP error response.
    """

    content: list[ContentBlock]
    """A list of content objects that represent the unstructured result of the tool call."""

    # OD-1 alternative: Unset-sentinel default distinguishing wire-absent from
    # explicit null (needs client + existing-test carve-outs)
    structured_content: Any = None
    """An optional JSON value that represents the structured result of the tool call.

    On 2026-07-28 sessions this can be any JSON value (object, array, string,
    number, boolean, or null) that conforms to the tool's output schema if one is
    defined; 2025-06-18 and 2025-11-25 restrict it to a JSON object on the wire.
    """

    is_error: bool = False
    """Whether the tool call ended in an error.

    If not set, this is assumed to be false (the call was successful).
    """


class ToolListChangedNotification(Notification[NotificationParams | None, Literal["notifications/tools/list_changed"]]):
    """An optional notification from the server to the client, informing it that the list
    of tools it offers has changed.
    """

    method: Literal["notifications/tools/list_changed"] = "notifications/tools/list_changed"
    params: NotificationParams | None = None


LoggingLevel = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]


class SetLevelRequestParams(RequestParams):
    """Parameters for setting the logging level.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    level: LoggingLevel
    """The level of logging that the client wants to receive from the server."""


class SetLevelRequest(Request[SetLevelRequestParams, Literal["logging/setLevel"]]):
    """A request from the client to the server, to enable or adjust logging.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    <= 2025-11-25. On 2026-07-28 sessions the client opts in to log messages
    per-request via the `io.modelcontextprotocol/logLevel` key in `_meta`
    instead.
    """

    method: Literal["logging/setLevel"] = "logging/setLevel"
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


class LoggingMessageNotification(Notification[LoggingMessageNotificationParams, Literal["notifications/message"]]):
    """Notification of a log message passed from server to client."""

    method: Literal["notifications/message"] = "notifications/message"
    params: LoggingMessageNotificationParams


IncludeContext = Literal["none", "thisServer", "allServers"]


class ModelHint(MCPModel):
    """Hints to use for model selection."""

    name: str | None = None
    """A hint for a model name."""


class ModelPreferences(MCPModel):
    """The server's preferences for model selection, requested by the client during
    sampling.

    Because LLMs can vary along multiple dimensions, choosing the "best" model is
    rarely straightforward. Different models excel in different areas—some are
    faster but less capable, others are more capable but more expensive, and so
    on. This interface allows servers to express their priorities across multiple
    dimensions to help clients make an appropriate selection for their use case.

    These preferences are always advisory. The client MAY ignore them. It is also
    up to the client to decide how to interpret these preferences and how to
    balance them against other considerations.
    """

    hints: list[ModelHint] | None = None
    """
    Optional hints to use for model selection.

    If multiple hints are specified, the client MUST evaluate them in order
    (such that the first match is taken).

    The client SHOULD prioritize these hints over the numeric priorities, but
    MAY still use the priorities to select from ambiguous matches.
    """

    cost_priority: float | None = None
    """
    How much to prioritize cost when selecting a model. A value of 0 means cost
    is not important, while a value of 1 means cost is the most important
    factor.
    """

    speed_priority: float | None = None
    """
    How much to prioritize sampling speed (latency) when selecting a model. A
    value of 0 means speed is not important, while a value of 1 means speed is
    the most important factor.
    """

    intelligence_priority: float | None = None
    """
    How much to prioritize intelligence and capabilities when selecting a
    model. A value of 0 means intelligence is not important, while a value of 1
    means intelligence is the most important factor.
    """


class ToolChoice(MCPModel):
    """Controls tool usage behavior during sampling.

    Allows the server to specify whether and how the LLM should use tools
    in its response.
    """

    mode: Literal["auto", "required", "none"] | None = None
    """
    Controls when tools are used:
    - "auto": Model decides whether to use tools (default)
    - "required": Model MUST use at least one tool before completing
    - "none": Model should not use tools
    """


class CreateMessageRequestParams(RequestParams):
    """Parameters for creating a message."""

    messages: list[SamplingMessage]
    model_preferences: ModelPreferences | None = None
    """
    The server's preferences for which model to select. The client MAY ignore
    these preferences.
    """
    system_prompt: str | None = None
    """An optional system prompt the server wants to use for sampling."""
    include_context: IncludeContext | None = None
    """
    A request to include context from one or more MCP servers (including the caller), to
    be attached to the prompt.
    """
    temperature: float | None = None
    max_tokens: int
    """The maximum number of tokens to sample, as requested by the server."""
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] | None = None
    """Optional metadata to pass through to the LLM provider."""
    tools: list[Tool] | None = None
    """
    Tool definitions for the LLM to use during sampling.
    Requires clientCapabilities.sampling.tools to be present.
    """
    tool_choice: ToolChoice | None = None
    """
    Controls tool usage behavior.
    Requires clientCapabilities.sampling.tools and the tools parameter to be present.
    """
    task: TaskMetadata | None = None
    """
    If set, requests task-augmented execution for this request (protocol
    2025-11-25 only). Removed in 2026-07-28: receivers on that version MUST
    ignore it.
    """


class CreateMessageRequest(Request[CreateMessageRequestParams, Literal["sampling/createMessage"]]):
    """A request from the server to sample an LLM via the client."""

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    params: CreateMessageRequestParams


StopReason = Literal["endTurn", "stopSequence", "maxTokens", "toolUse"] | str


class CreateMessageResult(Result):
    """The client's response to a sampling/createMessage request from the server.

    This is the backwards-compatible version that returns single content (no arrays).
    Used when the request does not include tools.
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

    This version supports array content for tool use flows.
    """

    role: Role
    """The role of the message sender (typically 'assistant' for LLM responses)."""
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """
    Response content. May be a single content block or an array.
    May include ToolUseContent if stop_reason is 'toolUse'.
    """
    model: str
    """The name of the model that generated the message."""
    stop_reason: StopReason | None = None
    """
    The reason why sampling stopped, if known.
    'toolUse' indicates the model wants to use a tool.
    """

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """Returns the content as a list of content blocks, regardless of whether
        it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class ResourceTemplateReference(MCPModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"] = "ref/resource"
    uri: str
    """The URI or URI template of the resource."""


# Deliberately flat on MCPModel, not BaseMetadata, despite the 2025-06-18+
# schemas declaring the BaseMetadata interface as a base: inheritance would
# reorder dump keys (type, name) -> (name, title, type), changing emitted bytes
# for existing callers.
class PromptReference(MCPModel):
    """Identifies a prompt."""

    type: Literal["ref/prompt"] = "ref/prompt"
    name: str
    """The name of the prompt or prompt template."""
    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display.
    """


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
    """Parameters for completion requests."""

    ref: ResourceTemplateReference | PromptReference
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
    """
    The total number of completion options available. This can exceed the number of
    values actually sent in the response.
    """
    has_more: bool | None = None
    """
    Indicates whether there are additional completion options beyond those provided in
    the current response, even if the exact total is unknown.
    """


class CompleteResult(Result):
    """The server's response to a completion/complete request."""

    completion: Completion


class ListRootsRequest(Request[RequestParams | None, Literal["roots/list"]]):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    method: Literal["roots/list"] = "roots/list"
    params: RequestParams | None = None


class Root(MCPModel):
    """Represents a root directory or file that the server can operate on."""

    uri: FileUrl
    """
    The URI identifying the root. This *must* start with file:// for now.
    This restriction may be relaxed in future versions of the protocol to allow
    other URI schemes.
    """
    name: str | None = None
    """
    An optional name for the root. This can be used to provide a human-readable
    identifier for the root, which may be useful for display purposes or for
    referencing the root in other parts of the application.
    """
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ListRootsResult(Result):
    """The client's response to a roots/list request from the server.

    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    roots: list[Root]


class RootsListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/roots/list_changed"]]
):
    """A notification from the client to the server, informing it that the list of
    roots has changed.

    This notification should be sent whenever the client adds, removes, or
    modifies any root. The server should then request an updated list of roots
    using the ListRootsRequest.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    method: Literal["notifications/roots/list_changed"] = "notifications/roots/list_changed"
    params: NotificationParams | None = None


class CancelledNotificationParams(NotificationParams):
    """Parameters for cancellation notifications."""

    request_id: RequestId | None = None
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    """
    reason: str | None = None
    """An optional string describing the reason for the cancellation."""


class CancelledNotification(Notification[CancelledNotificationParams, Literal["notifications/cancelled"]]):
    """This notification can be sent by either side to indicate that it is canceling a
    previously-issued request.
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
    """A notification from the server to the client, informing it that a URL mode
    elicitation has been completed.

    Clients MAY use the notification to automatically retry requests that received a
    URLElicitationRequiredError, update the user interface, or otherwise continue
    an interaction. However, because delivery of the notification is not guaranteed,
    clients must not wait indefinitely for a notification from the server.
    """

    method: Literal["notifications/elicitation/complete"] = "notifications/elicitation/complete"
    params: ElicitCompleteNotificationParams


# Type for elicitation schema - a JSON Schema dict
ElicitRequestedSchema: TypeAlias = dict[str, Any]
"""Schema for elicitation requests."""


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
    """
    A restricted subset of JSON Schema defining the structure of the expected response.
    Only top-level properties are allowed, without nesting.
    """

    task: TaskMetadata | None = None
    """If specified, the caller is requesting task-augmented execution for this request.

    2025-11-25 sessions only; removed in protocol 2026-07-28 (tasks continue as an
    extension).
    """


class ElicitRequestURLParams(RequestParams):
    """Parameters for URL mode elicitation requests.

    URL mode directs users to external URLs for sensitive out-of-band interactions
    like OAuth flows, credential collection, or payment processing.
    """

    mode: Literal["url"] = "url"
    """The elicitation mode (always "url" for this type)."""

    message: str
    """The message to present to the user explaining why the interaction is needed."""

    url: str
    """The URL that the user should navigate to."""

    elicitation_id: str
    """The ID of the elicitation, which must be unique within the context of the server.

    The client MUST treat this ID as an opaque value.
    """

    task: TaskMetadata | None = None
    """If specified, the caller is requesting task-augmented execution for this request.

    2025-11-25 sessions only; removed in protocol 2026-07-28 (tasks continue as an
    extension).
    """


# Union type for elicitation request parameters
ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams
"""Parameters for elicitation requests - either form or URL mode."""


class ElicitRequest(Request[ElicitRequestParams, Literal["elicitation/create"]]):
    """A request from the server to elicit information from the client."""

    method: Literal["elicitation/create"] = "elicitation/create"
    params: ElicitRequestParams


class ElicitResult(Result):
    """The client's response to an elicitation request."""

    action: Literal["accept", "decline", "cancel"]
    """
    The user action in response to the elicitation.
    - "accept": User submitted the form/confirmed the action (or consented to URL navigation)
    - "decline": User explicitly declined the action
    - "cancel": User dismissed without making an explicit choice
    """

    content: dict[str, str | int | float | bool | list[str] | None] | None = None
    """
    The submitted form data, only present when action is "accept" in form mode.
    Contains values matching the requested schema. Values can be strings, integers, floats,
    booleans, arrays of strings, or null.
    For URL mode, this field is omitted.
    """


class ElicitationRequiredErrorData(MCPModel):
    """Error data for the URL-elicitation-required error (code -32042, ``URL_ELICITATION_REQUIRED``).

    Servers return this when a request cannot be processed until one or more
    URL mode elicitations are completed.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating 2025-11-25.
    """

    elicitations: list[ElicitRequestURLParams]
    """List of URL mode elicitations that must be completed."""


InputRequest: TypeAlias = CreateMessageRequest | ListRootsRequest | ElicitRequest
"""A single server-initiated input request embedded in a multi-round-trip flow (2026-07-28).

Values of the ``InputRequests`` map carried by ``InputRequiredResult.input_requests``.
On 2026-07-28 sessions these embedded payloads replace the standalone
server-to-client JSON-RPC requests of earlier protocol versions; each member's
required ``method`` literal is the discriminating tag.
"""

InputRequests: TypeAlias = dict[str, InputRequest]
"""A map of server-initiated requests that the client must fulfill (2026-07-28).

Keys are server-assigned identifiers; values are the embedded request payloads
(`CreateMessageRequest | ListRootsRequest | ElicitRequest`). Carried by
`InputRequiredResult.input_requests` in the multi-round-trip (MRTR) flow; the
`io.modelcontextprotocol/tasks` extension reuses the same type for its
`inputRequests` fields.
"""

InputResponse: TypeAlias = CreateMessageResult | CreateMessageResultWithTools | ListRootsResult | ElicitResult
"""A client response to a single server-initiated input request (2026-07-28, MRTR).

Values never travel as top-level JSON-RPC results: they appear as entries of an
``InputResponses`` map — in ``inputResponses`` on retried client requests, and in
the tasks extension's ``tasks/update`` params. ``CreateMessageResultWithTools`` is
the SDK's array-content split of the schema's single ``CreateMessageResult`` arm;
the wire union has exactly three arms.
"""

InputResponses: TypeAlias = dict[str, InputResponse]
"""A map of client responses to server-initiated input requests (2026-07-28, MRTR).

Keys correspond to the keys of the ``InputRequests`` map the server sent in its
``InputRequiredResult``; values are the client's result for each request. Reused
verbatim by the ``io.modelcontextprotocol/tasks`` extension (``tasks/update``
params), which keys responses to currently-outstanding input requests.
"""


class InputRequiredResult(Result):
    """The server needs additional input before the original request can complete (2026-07-28).

    Returned in place of the normal result of an interactive client request
    (`tools/call`, `prompts/get`, `resources/read`). The client fulfills
    `input_requests` and retries the original request, carrying the matching
    responses and the echoed `request_state`.

    At least one of `input_requests` / `request_state` is present on the wire
    (spec MUST; not enforced by the model — inbound stays lenient).
    """

    input_requests: InputRequests | None = None
    """Requests issued by the server that must be completed before the client can retry the original request.

    Keys are server-assigned identifiers; values are the embedded request payloads.
    """

    request_state: str | None = None
    """Opaque state to pass back to the server when the client retries the original request.

    The client must treat this as an opaque blob and must not interpret it in any way.
    """


# Deferred-annotation completion: InputResponseRequestParams (and its consumers)
# reference InputResponses, which is only bound above. Explicit rebuilds keep
# model completion at import time rather than first use.
InputResponseRequestParams.model_rebuild()
ReadResourceRequestParams.model_rebuild()
GetPromptRequestParams.model_rebuild()
CallToolRequestParams.model_rebuild()

# Top-level message unions, declared last so every member class is bound.
# Membership is the superset across all known protocol versions; which members
# are valid on a given session's negotiated version is recorded in the
# per-version method tables (mcp.types._versions), never enforced here —
# inbound parsing stays superset-lenient on every session.

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

The 2025-11-25 task requests are deliberately excluded (types-only, never
dispatched).
"""

# OD-12 alternative: method-discriminated adapter (rejects method-less dicts).
client_request_adapter = TypeAdapter[ClientRequest](ClientRequest)


ClientNotification = (
    CancelledNotification | ProgressNotification | InitializedNotification | RootsListChangedNotification
)
"""Notifications sent from the client to the server.

All four members are valid on every released version (2024-11-05 through
2025-11-25); on 2026-07-28 sessions only ``CancelledNotification`` and
``ProgressNotification`` are. The 2025-11-25 ``TaskStatusNotification`` is
deliberately excluded (types-only, never dispatched).
"""

# OD-12 alternative: method-discriminated adapter (rejects method-less dicts).
client_notification_adapter = TypeAdapter[ClientNotification](ClientNotification)


ClientResult = EmptyResult | CreateMessageResult | CreateMessageResultWithTools | ListRootsResult | ElicitResult
client_result_adapter = TypeAdapter[ClientResult](ClientResult)


ServerRequest = PingRequest | CreateMessageRequest | ListRootsRequest | ElicitRequest
"""Union of standalone JSON-RPC requests a server can send to a client.

Live on 2024-11-05 through 2025-11-25 sessions only: the 2026-07-28 protocol
removes the standalone server-to-client request channel. On 2026-07-28
sessions, sampling, roots, and elicitation requests are instead embedded in
``InputRequiredResult.input_requests``, and ping is removed entirely, so the
server-request method set for that version is empty.
"""

# OD-12 alternative: method-discriminated adapter (rejects method-less dicts).
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

The 2025-11-25 ``TaskStatusNotification`` is deliberately excluded (types-only,
never dispatched).
"""

# OD-12 alternative: method-discriminated adapter (rejects method-less dicts).
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
    | InputRequiredResult
)
"""Union of every result payload a server can return for a client request.

Spans all supported protocol versions: `InitializeResult` is only valid on
pre-2026-07-28 sessions; `DiscoverResult` and `InputRequiredResult` only on
2026-07-28 sessions. Member order matters only between `EmptyResult` and
`InputRequiredResult`, the two members with no required fields: a payload that
sets none of `InputRequiredResult`'s own fields (e.g. a bare ``{}``) parses as
whichever of the two comes first, so `EmptyResult` is placed before it. Every
other member has a required field and is matched by content regardless of
position.
"""
server_result_adapter = TypeAdapter[ServerResult](ServerResult)
