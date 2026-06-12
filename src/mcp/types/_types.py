from __future__ import annotations

from typing import Annotated, Any, Final, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, FileUrl, TypeAdapter
from pydantic.alias_generators import to_camel
from typing_extensions import NotRequired, TypedDict

from mcp.types.jsonrpc import RequestId

LATEST_PROTOCOL_VERSION: Final[str] = "2025-11-25"
"""The newest protocol version this SDK can negotiate.

You can find the latest specification at https://modelcontextprotocol.io/specification/latest.

This is deliberately `Final[str]`, not a `Literal`: the value advances when SDK
support for a newer protocol revision ships, so callers must not narrow on the
current value.
"""

DEFAULT_NEGOTIATED_VERSION: Final[str] = "2025-03-26"
"""The default negotiated version of the Model Context Protocol when no version is specified.

We need this to satisfy the MCP specification, which requires the server to assume a specific version if none is
provided by the client.

See the "Protocol Version Header" at
https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#protocol-version-header.
"""

ProgressToken = str | int
"""A progress token, used to associate progress notifications with the original request.

Identical in every supported protocol version: a string or a number (the JSON form of
every schema version pins the numeric kind to integer; null is never allowed). A
requester places the token in a request's optional ``_meta.progressToken`` slot; the
receiver attaches the same token as the required ``progressToken`` field of any
``notifications/progress`` it chooses to emit, correlating the notification stream
back to the original request.
"""

Role = Literal["user", "assistant"]
"""The sender or recipient of messages and data in a conversation.

The value set is identical in every protocol version (2024-11-05 through 2026-07-28).
"""

IconTheme = Literal["light", "dark"]
"""Theme an icon is designed for. Wire values of ``Icon.theme`` (2025-11-25+)."""


class MCPModel(BaseModel):
    """Base class for all MCP protocol types."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Meta: TypeAlias = dict[str, Any]

PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
"""Reserved request `_meta` key: the MCP protocol version for this request (2026-07-28).

The wire boundary injects this key when it is absent on 2026-07-28 emission
(a caller-set value is never overwritten). For the HTTP transport its value
must match the `MCP-Protocol-Version` header.
"""

CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
"""Reserved request `_meta` key: the client `Implementation` making the request (2026-07-28).

Caller-supplied: the wire boundary never synthesizes client identity, so the
caller (normally the session layer) must set this key before a 2026-07-28
request is serialized; emission without it is refused.
"""

CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
"""Reserved request `_meta` key: the client's per-request `ClientCapabilities` (2026-07-28).

Caller-supplied: the wire boundary never synthesizes client identity, so the
caller (normally the session layer) must set this key before a 2026-07-28
request is serialized; emission without it is refused. Servers must not infer
capabilities from prior requests.
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
    ``extra_items=Any``. On 2026-07-28 requests the reserved keys are required:
    the wire boundary injects the protocol version when absent, refuses
    emission unless the caller has supplied the client info and client
    capabilities keys, and rejects inbound requests missing any of the three.
    Read or set them via the ``*_META_KEY`` constants.
    """

    progress_token: NotRequired[ProgressToken]
    """
    If specified, the caller requests out-of-band progress notifications for
    this request (as represented by notifications/progress). The value of this
    parameter is an opaque token that will be attached to any subsequent
    notifications. The receiver is not obligated to provide these notifications.
    """


class RequestParams(MCPModel):
    """Common params for any request."""

    meta: RequestParamsMeta | None = Field(alias="_meta", default=None)
    """Metadata reserved by MCP for protocol-level concerns (wire name `_meta`).

    Carries the optional progress token and, on 2026-07-28 sessions, the reserved
    `io.modelcontextprotocol/*` keys (protocolVersion, clientInfo,
    clientCapabilities, plus the deprecated logLevel). The field is required on
    the wire for 2026-07-28 requests: the wire boundary materializes it and
    injects the protocol version, but the client info and client capabilities
    keys must be caller-supplied (see `RequestParamsMeta`).
    """


class PaginatedRequestParams(RequestParams):
    """Common params for paginated requests."""

    cursor: str | None = None
    """An opaque token representing the current pagination position.

    If provided, the server should return results starting after this cursor.
    """


class NotificationParams(MCPModel):
    """Common params for any notification."""

    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


RequestParamsT = TypeVar("RequestParamsT", bound=RequestParams | dict[str, Any] | None)
NotificationParamsT = TypeVar("NotificationParamsT", bound=NotificationParams | dict[str, Any] | None)
MethodT = TypeVar("MethodT", bound=str)


class Request(MCPModel, Generic[RequestParamsT, MethodT]):
    """Base class for JSON-RPC requests.

    Concrete requests subclass this as
    ``Request[<ParamsType>, Literal["<method>"]]`` and default the method
    literal. The JSON-RPC envelope (``jsonrpc``, ``id``) is not part of this
    payload type; it is attached by the session layer (see ``mcp.types.jsonrpc``).
    """

    method: MethodT
    """The protocol method name identifying this request."""

    params: RequestParamsT
    """The request's parameters; concrete subclasses set the per-method type and
    requiredness."""


class PaginatedRequest(Request[PaginatedRequestParams | None, MethodT], Generic[MethodT]):
    """Base class for paginated requests, matching the schema's PaginatedRequest interface."""

    params: PaginatedRequestParams | None = None
    """Pagination params.

    Required on the wire for 2026-07-28 peers (because `_meta` is required
    there); the wire boundary materializes the container, but the reserved
    `_meta` identity keys must be caller-supplied (see `RequestParamsMeta`).
    Optional on all earlier versions.
    """


class Notification(MCPModel, Generic[NotificationParamsT, MethodT]):
    """Base class for JSON-RPC notifications."""

    method: MethodT
    """The notification method name."""

    params: NotificationParamsT
    """The notification's parameters.

    Optional on the wire in every protocol version; concrete subclasses narrow
    this to their params model, or to `NotificationParams | None = None` for
    parameterless notifications.
    """


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

    `None` means the peer did not send the field (pre-2026-07-28 peers never do),
    which the spec defines as equivalent to "complete". On 2026-07-28 sessions the
    SDK injects this at the wire boundary when unset; handlers normally never set
    it.

    On sessions negotiated at 2025-11-25 or older, setting this field on a
    result whose body would otherwise be EMPTY (`{}`) makes some deployed
    clients reject the response: TypeScript SDK clients (every released
    line) validate empty results strictly, as does the Rust SDK. Bodies
    with other fields are unaffected — deployed peers ignore unknown keys.
    Leave this field unset on pre-2026-07-28 sessions; the SDK does not
    strip it for you.
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

    Both fields are required on the wire for 2026-07-28 peers; the SDK supplies
    defaults at the wire boundary when a handler leaves them unset. The fields do
    not exist on the wire for 2025-11-25 and earlier sessions.
    """

    ttl_ms: int | None = None
    """How long, in milliseconds, the client MAY cache this response before
    re-fetching — analogous to HTTP Cache-Control max-age.

    0 means the response SHOULD be considered immediately stale; a positive value
    means the client SHOULD consider the result fresh for that many milliseconds.
    Must be non-negative. `None` means the handler left it unset; on 2026-07-28
    sessions the SDK supplies a value at emit time.
    """

    cache_scope: Literal["public", "private"] | None = None
    """Intended scope of the cached response, analogous to HTTP
    `Cache-Control: public` vs `Cache-Control: private`.

    With "public", any client or intermediary (e.g. a shared gateway or proxy)
    MAY cache the response and serve it to any user; with "private", only the
    requesting user's client MAY cache it, and shared caches MUST NOT serve a
    cached copy to a different user. `None` means the handler left it unset; on
    2026-07-28 sessions the SDK supplies a value at emit time.
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
    """Describes the MCP implementation (``clientInfo`` / ``serverInfo``).

    On sessions negotiated at 2025-11-25 or earlier, this is carried once per
    session: client->server as ``InitializeRequestParams.client_info`` and
    server->client as ``InitializeResult.server_info``. On 2026-07-28 sessions it
    is carried per request in ``_meta["io.modelcontextprotocol/clientInfo"]`` and
    server->client as ``DiscoverResult.server_info``.

    Inherits ``name`` (required) and optional ``title`` from ``BaseMetadata``;
    only ``name`` and ``version`` are required on the wire in every protocol
    version.
    """

    version: str
    """The version of this implementation."""

    description: str | None = None
    """An optional human-readable description of what this implementation does.

    This can be used by clients or servers to provide context about their purpose
    and capabilities. For example, a server might describe the types of resources
    or tools it provides, while a client might describe its intended use case.
    """

    website_url: str | None = None
    """An optional URL of the website for this implementation."""

    icons: list[Icon] | None = None
    """Optional set of sized icons that the client can display in a user interface."""


class RootsCapability(MCPModel):
    """Capability for root operations.

    Deprecated as a whole in protocol 2026-07-28 (SEP-2577) but remains in the
    specification's deprecated-features registry; used on all earlier-version
    sessions.
    """

    list_changed: bool | None = None
    """Whether the client supports notifications for changes to the roots list.

    Removed in protocol 2026-07-28 (the `roots` capability there is an empty
    object); meaningful on 2025-11-25 and earlier sessions.
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
    """Sampling capability structure, allowing fine-grained capability advertisement.

    The `sampling` capability as a whole is deprecated in protocol 2026-07-28
    (SEP-2577) but its shape is unchanged there; used on all sessions.
    """

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

    Sent/received on sessions negotiating 2025-11-25 only (the experimental
    core tasks support; tasks continue as an extension in 2026-07-28).
    """


class TasksCancelCapability(MCPModel):
    """Capability for tasks cancel operations.

    Sent/received on sessions negotiating 2025-11-25 only (the experimental
    core tasks support; tasks continue as an extension in 2026-07-28).
    """


class TasksCreateMessageCapability(MCPModel):
    """Capability for task-augmented sampling/createMessage requests (2025-11-25 only)."""


class TasksSamplingCapability(MCPModel):
    """Task support for sampling-related requests (2025-11-25 only)."""

    create_message: TasksCreateMessageCapability | None = None
    """Whether the client supports task-augmented sampling/createMessage requests."""


class TasksCreateElicitationCapability(MCPModel):
    """Capability for task-augmented elicitation/create requests (2025-11-25 only)."""


class TasksElicitationCapability(MCPModel):
    """Task support for elicitation-related requests (2025-11-25 only)."""

    create: TasksCreateElicitationCapability | None = None
    """Whether the client supports task-augmented elicitation/create requests."""


class ClientTasksRequestsCapability(MCPModel):
    """Specifies which request types the client can augment with tasks (2025-11-25 only)."""

    sampling: TasksSamplingCapability | None = None
    """Task support for sampling-related requests."""

    elicitation: TasksElicitationCapability | None = None
    """Task support for elicitation-related requests."""


class ClientTasksCapability(MCPModel):
    """Capability for client task operations.

    Carried in `ClientCapabilities.tasks` on sessions negotiating 2025-11-25
    only: the `tasks` capability was introduced there as experimental core
    support and removed in protocol 2026-07-28 (tasks continue as an
    extension).
    """

    list: TasksListCapability | None = None
    """Whether this client supports tasks/list."""

    cancel: TasksCancelCapability | None = None
    """Whether this client supports tasks/cancel."""

    requests: ClientTasksRequestsCapability | None = None
    """Specifies which request types can be augmented with tasks."""


class ClientCapabilities(MCPModel):
    """Capabilities a client may support.

    Known capabilities are defined in the spec schema, but this is not a closed
    set: any client can define its own, additional capabilities. On protocol
    versions through 2025-11-25 this object is sent once, in `initialize`; on
    2026-07-28 sessions the SDK carries it in every request's `_meta` under
    "io.modelcontextprotocol/clientCapabilities".
    """

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
    """Present if the client supports task-augmented requests.

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
    """


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
    """Capability for task-augmented tools/call requests (2025-11-25 only)."""


class TasksToolsCapability(MCPModel):
    """Task support for tool-related requests (2025-11-25 only)."""

    call: TasksCallCapability | None = None
    """Whether the server supports task-augmented tools/call requests."""


class ServerTasksRequestsCapability(MCPModel):
    """Specifies which request types the server can augment with tasks (2025-11-25 only)."""

    tools: TasksToolsCapability | None = None
    """Task support for tool-related requests."""


class ServerTasksCapability(MCPModel):
    """Capability for server task operations.

    Carried in `ServerCapabilities.tasks` on sessions negotiating 2025-11-25
    only: the `tasks` capability was introduced there as experimental core
    support and removed in protocol 2026-07-28 (tasks continue as an
    extension).
    """

    list: TasksListCapability | None = None
    """Whether this server supports tasks/list."""

    cancel: TasksCancelCapability | None = None
    """Whether this server supports tasks/cancel."""

    requests: ServerTasksRequestsCapability | None = None
    """Specifies which request types can be augmented with tasks."""


class ServerCapabilities(MCPModel):
    """Capabilities that a server may support.

    Known capabilities are defined here, but this is not a closed set: any
    server can define its own, additional capabilities.
    """

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the server supports."""

    logging: LoggingCapability | None = None
    """Present if the server supports sending log messages to the client.

    Deprecated as of protocol version 2026-07-28 (SEP-2577); remains valid on
    earlier-version sessions.
    """

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
    """Present if the server supports task-augmented requests.

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
    """


# --- Removed in protocol 2026-07-28: the initialize/initialized handshake and ping.
# 2026-07-28 sessions use the server/discover flow plus per-request _meta instead.
# OD-2 alternative: move removed-method types to a lazily-aliased mcp.types.legacy module.


class InitializeRequestParams(RequestParams):
    """Parameters for the `initialize` request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    protocol_version: str
    """The latest version of the Model Context Protocol that the client supports.

    The client MAY decide to support older versions as well.
    """

    capabilities: ClientCapabilities
    """The capabilities the client supports."""

    client_info: Implementation
    """Information about the client implementation."""


class InitializeRequest(Request[InitializeRequestParams, Literal["initialize"]]):
    """This request is sent from the client to the server when it first connects, asking it
    to begin initialization.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25
    (2026-07-28 sessions replace the handshake with the `server/discover` flow plus
    per-request `_meta`).
    """

    method: Literal["initialize"] = "initialize"
    """The protocol method name (`initialize`)."""

    params: InitializeRequestParams
    """The initialization parameters (required in every protocol version that
    has this request)."""


class InitializeResult(Result):
    """After receiving an initialize request from the client, the server sends this response.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    The 2026-07-28 revision replaces the initialize handshake with `server/discover`
    (see `DiscoverResult`).
    """

    protocol_version: str
    """The version of the Model Context Protocol that the server wants to use.

    This may not match the version that the client requested. If the client
    cannot support this version, it MUST disconnect.
    """
    capabilities: ServerCapabilities
    """The capabilities of the server."""
    server_info: Implementation
    """Information about the server implementation."""
    instructions: str | None = None
    """Instructions describing how to use the server and its features.

    This can be used by clients to improve the LLM's understanding of available
    tools, resources, etc. It can be thought of like a "hint" to the model. For
    example, this information MAY be added to the system prompt.
    """


class InitializedNotification(Notification[NotificationParams | None, Literal["notifications/initialized"]]):
    """This notification is sent from the client to the server after initialization has
    finished.

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
    """A request from the client asking the server to advertise its supported
    protocol versions, capabilities, and other metadata (2026-07-28 only).

    Servers speaking 2026-07-28 MUST implement ``server/discover``; clients MAY
    call it but are not required to - version negotiation can also happen
    inline via per-request ``_meta``.
    """

    method: Literal["server/discover"] = "server/discover"
    params: RequestParams | None = None
    """Required on the 2026-07-28 wire (its ``_meta`` must carry the reserved
    ``io.modelcontextprotocol/*`` keys). The wire boundary materializes
    ``params._meta`` and injects the protocol version, but the client info and
    client capabilities keys must be caller-supplied — serialization refuses
    the request without them (see `RequestParamsMeta`).
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
    """Optional annotations for the client.

    The client can use annotations to inform how objects are used or displayed.
    Carried as the optional ``annotations`` field of resources, resource
    templates, and content blocks in every protocol version (on 2024-11-05 the
    same object is carried anonymously via the schema's ``Annotated`` base
    interface).
    """

    audience: list[Role] | None = None
    """Describes who the intended audience of this object or data is.

    It can include multiple entries to indicate content useful for multiple
    audiences (e.g., ``["user", "assistant"]``).
    """

    priority: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    """Describes how important this data is for operating the server.

    A value of 1 means "most important," and indicates that the data is
    effectively required, while 0 means "least important," and indicates that
    the data is entirely optional.
    """


class Resource(BaseMetadata):
    """A known resource that the server is capable of reading."""

    uri: str
    """The URI of this resource."""

    description: str | None = None
    """A description of what this resource represents.

    This can be used by clients to improve the LLM's understanding of available
    resources. It can be thought of like a "hint" to the model.
    """

    mime_type: str | None = None
    """The MIME type of this resource, if known."""

    size: int | None = None
    """The size of the raw resource content, in bytes (i.e., before base64 encoding or any tokenization), if known.

    This can be used by Hosts to display file sizes and estimate context window usage.
    """

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
    """A description of what this template is for.

    This can be used by clients to improve the LLM's understanding of available
    resources. It can be thought of like a "hint" to the model.
    """

    mime_type: str | None = None
    """The MIME type for all resources that match this template.

    This should only be included if all resources matching this template have the same type.
    """

    icons: list[Icon] | None = None
    """An optional set of sized icons that the client can display in a user interface."""

    annotations: Annotations | None = None
    """Optional annotations for the client."""

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
    """Parameters for a `resources/read` request."""

    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server
    how to interpret it.
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

    On protocol versions up to 2025-11-25, servers may send this spontaneously,
    without any previous subscription from the client. On 2026-07-28 sessions,
    delivery is opt-in: the server must not send it unless the client requested it
    via SubscriptionFilter.resources_list_changed on a subscriptions/listen request.
    """

    method: Literal["notifications/resources/list_changed"] = "notifications/resources/list_changed"
    params: NotificationParams | None = None


# --- Removed in protocol 2026-07-28: per-URI resource subscribe/unsubscribe.
# 2026-07-28 sessions manage resource subscriptions via subscriptions/listen instead.


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
    """Parameters for a resources/unsubscribe request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    uri: str
    """The URI of the resource to unsubscribe from."""


class UnsubscribeRequest(Request[UnsubscribeRequestParams, Literal["resources/unsubscribe"]]):
    """Sent from the client to request cancellation of resources/updated notifications
    from the server. This should follow a previous resources/subscribe request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    2026-07-28 peers manage resource subscriptions declaratively via subscriptions/listen
    (SubscriptionsListenRequest) instead.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    params: UnsubscribeRequestParams


class ResourceUpdatedNotificationParams(NotificationParams):
    """Parameters for a `notifications/resources/updated` notification."""

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

    On sessions negotiated at 2025-11-25 or earlier, this should only be sent if the
    client previously sent a `resources/subscribe` request. On 2026-07-28 sessions,
    it is only sent for resources the client opted in to via the
    `resourceSubscriptions` field of a `subscriptions/listen` request.
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

    # OD-9 alternative: a parse-side extra="allow" layer for every extension-carrying
    # model instead of this single carve-out.
    model_config = ConfigDict(extra="allow")

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
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ListPromptsResult(PaginatedResult, CacheableResult):
    """The server's response to a prompts/list request from the client."""

    prompts: list[Prompt]
    """The list of prompts and prompt templates the server offers."""


class GetPromptRequestParams(InputResponseRequestParams):
    """Parameters for a prompts/get request."""

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
    """Content-type discriminator; always "text"."""
    text: str
    """The text content of the message."""
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


class ImageContent(MCPModel):
    """An image provided to or from an LLM."""

    type: Literal["image"] = "image"
    """Discriminator for image content."""
    data: str
    """The base64-encoded image data."""
    mime_type: str
    """
    The MIME type of the image. Different providers may support different
    image types.
    """
    annotations: Annotations | None = None
    """Optional annotations for the client."""
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification's "General fields: _meta" section for notes on _meta usage."""


class AudioContent(MCPModel):
    """Audio provided to or from an LLM."""

    type: Literal["audio"] = "audio"
    """Discriminator identifying this content block as audio."""
    data: str
    """The base64-encoded audio data."""
    mime_type: str
    """
    The MIME type of the audio. Different providers may support different
    audio types.
    """
    annotations: Annotations | None = None
    """Optional annotations for the client."""
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
"""Content block types allowed in sampling messages.

This is the widest (2025-11-25 / 2026-07-28) membership. On older sessions only
a subset is legal on the wire (text/image on 2024-11-05; text/image/audio on
2025-03-26 and 2025-06-18); the type itself does not narrow per version.

Deprecated (with the rest of the sampling family) as of protocol 2026-07-28 by
SEP-2577; remains in the specification for at least twelve months and stays
fully supported here for all pre-2026-07-28 sessions.
"""

SamplingContent: TypeAlias = TextContent | ImageContent | AudioContent
"""Basic content types for sampling responses (without tool use).

Used for backwards-compatible CreateMessageResult when tools are not used.
"""


class SamplingMessage(MCPModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    """The role of the message sender ("user" or "assistant")."""
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
    """Discriminator for embedded resource content blocks."""
    resource: TextResourceContents | BlobResourceContents
    """The text or binary contents of the embedded resource."""
    annotations: Annotations | None = None
    """Optional annotations for the client."""
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
    """Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    role: Role
    """The sender or recipient of this message in the conversation."""
    content: ContentBlock
    """The message content: text, image, audio, a resource link, or an embedded resource."""


class GetPromptResult(Result):
    """The server's response to a prompts/get request from the client."""

    description: str | None = None
    """An optional description for the prompt."""
    messages: list[PromptMessage]
    """The messages composing the prompt, in the order they should be presented."""


class PromptListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/prompts/list_changed"]]
):
    """An optional notification from the server to the client, informing it that the list
    of prompts it offers has changed.

    On sessions negotiated at 2025-11-25 or earlier, servers may send this
    spontaneously, without any previous subscription from the client. On
    2026-07-28 sessions delivery is opt-in: the server MUST NOT send it unless
    the client requested it via ``subscriptions/listen``
    (``SubscriptionFilter.prompts_list_changed``).
    """

    method: Literal["notifications/prompts/list_changed"] = "notifications/prompts/list_changed"
    params: NotificationParams | None = None


# --- Removed in protocol 2026-07-28: the experimental 2025-11-25 task system
# (task-augmented requests, tasks/get, tasks/cancel, tasks/result, tasks/list,
# notifications/tasks/status). Tasks continue at 2026-07-28 as the
# io.modelcontextprotocol/tasks extension. These types are kept for 2025-11-25
# sessions; the tasks/* methods are deliberately not members of any request
# union or method table — custom task support dispatches them explicitly.
# OD-3 alternative: also ship the extension's own task types under mcp/extensions/tasks/.


class ToolExecution(MCPModel):
    """Execution-related properties for a tool.

    Defined in the 2025-11-25 schema only (introduced with the experimental
    core tasks support; the 2026-07-28 tasks extension has no per-tool
    execution declaration). Unlike the task types below, it rides
    `tools/list` results rather than a tasks method, and serialization never
    strips it — see `Tool.execution`.
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
    2025-11-25 (tasks continue as an extension, which has no request-side
    task-creation metadata).
    """

    ttl: int | None = None
    """Requested duration in milliseconds to retain task from creation."""


class RelatedTaskMetadata(MCPModel):
    """Metadata for associating messages with a task.

    Include this in the ``_meta`` field under the key
    ``io.modelcontextprotocol/related-task``.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension).
    """

    task_id: str
    """The task identifier this message is associated with."""


TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]
"""The status of a task.

Removed in protocol 2026-07-28; sent/received on sessions negotiating
2025-11-25 (tasks continue as an extension).

Values: "working" (the request is currently being processed); "input_required"
(the task is waiting for input, e.g. elicitation or sampling); "completed" (the
request completed successfully and results are available); "failed" (the
associated request did not complete successfully — for tool calls this includes
results with ``isError`` set to true); "cancelled" (the request was cancelled
before completion).

The ``io.modelcontextprotocol/tasks`` extension uses the identical value set but
reserves "failed" for JSON-RPC errors during execution: there, a tool result
with ``isError: true`` is a "completed" task carrying that result. Code that
classifies task outcomes must branch on which surface was negotiated.
"""


class Task(MCPModel):
    """Data associated with a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension).
    """

    task_id: str
    """The task identifier."""

    status: TaskStatus
    """Current task state."""

    status_message: str | None = None
    """Optional human-readable message describing the current task state.

    This can provide context for any status, including reasons for "cancelled"
    status, summaries for "completed" status, and diagnostic information for
    "failed" status (e.g., error details, what went wrong).
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

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension). Returned immediately in lieu
    of the request's normal result when the caller requested task-augmented
    execution via ``params.task``; the actual result is retrieved later via
    ``tasks/result``.
    """

    task: Task
    """The task created for the augmented request."""


class GetTaskRequestParams(RequestParams):
    """Parameters for a tasks/get request."""

    task_id: str
    """The task identifier to query."""


class GetTaskRequest(Request[GetTaskRequestParams, Literal["tasks/get"]]):
    """A request to retrieve the state of a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (the io.modelcontextprotocol/tasks extension keeps an identical
    wire shape). Types-only: not a member of any SDK request union or dispatch
    table — custom task implementations register a handler for "tasks/get"
    explicitly.
    """

    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


class GetTaskResult(Result, Task):
    """The response to a tasks/get request.

    The task state merged flat into the result object. Status-only: the
    underlying request's payload is retrieved separately via tasks/result.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension).
    """


class CancelTaskRequestParams(RequestParams):
    """Parameters for a `tasks/cancel` request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension).
    """

    task_id: str
    """The task identifier to cancel."""


class CancelTaskRequest(Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    """A request to cancel a task.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension). On 2025-11-25 sessions this
    request flows in both directions (client-hosted tasks). Types-only: not a
    member of any SDK request union or adapter; custom 2025-11-25 task support
    registers a handler explicitly.
    """

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class CancelTaskResult(Result, Task):
    """The response to a ``tasks/cancel`` request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension). The wire shape is the
    intersection ``Result & Task``: the complete post-cancellation task
    snapshot (2025-11-25 required the receiver to transition the task before
    responding).
    """


class TaskStatusNotificationParams(NotificationParams, Task):
    """Parameters for a `notifications/tasks/status` notification.

    The 2025-11-25 schema defines these params as the intersection
    `NotificationParams & Task`: the full task state is inlined alongside the
    optional `_meta` field.
    """


class TaskStatusNotification(Notification[TaskStatusNotificationParams, Literal["notifications/tasks/status"]]):
    """An optional notification from the receiver to the requestor, informing them
    that a task's status has changed. Receivers are not required to send these
    notifications.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension, where the equivalent
    notification is `notifications/tasks`).
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
    2025-11-25 (tasks continue as an extension, which delivers terminal
    payloads inline in tasks/get responses instead).
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

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension, which delivers payloads inline
    in ``tasks/get`` instead).
    """


class ListTasksRequest(PaginatedRequest[Literal["tasks/list"]]):
    """A request to retrieve a list of tasks.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (tasks continue as an extension, which deliberately drops
    tasks/list).
    """

    method: Literal["tasks/list"] = "tasks/list"


class ListTasksResult(PaginatedResult):
    """The response to a tasks/list request.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating
    2025-11-25 (the tasks extension has no list operation).
    """

    tasks: list[Task]
    """The list of tasks."""


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
    """A human-readable description of the tool.

    This can be used by clients to improve the LLM's understanding of available
    tools. It can be thought of like a "hint" to the model.
    """

    input_schema: dict[str, Any]
    """A JSON Schema object defining the expected parameters for the tool.

    Tool arguments are always JSON objects, so `type: "object"` is required at the
    root. On 2026-07-28 sessions any JSON Schema 2020-12 keyword may appear
    alongside `type` (composition, conditional, and reference keywords included);
    earlier protocol versions define only `type`, `properties`, and `required`
    (plus `$schema` from 2025-11-25). Defaults to JSON Schema 2020-12 when no
    explicit `$schema` is provided.
    """

    execution: ToolExecution | None = None
    """Execution-related properties for this tool.

    Defined in the 2025-11-25 schema only; removed in protocol 2026-07-28
    (tasks continue as an extension with no per-tool execution declaration).
    Serialization never strips it: like `icons` and `title` on versions that
    predate them, a set value is emitted at every version — peers ignore tool
    fields they do not recognize — so leaving it unset outside 2025-11-25
    sessions is up to the caller.
    """

    output_schema: dict[str, Any] | None = None
    """An optional JSON Schema object defining the structure of the tool's output
    returned in the structured_content field of a CallToolResult.

    Restricted to `type: "object"` at the root on 2025-06-18 and 2025-11-25
    sessions; any valid JSON Schema 2020-12 on 2026-07-28. Defaults to JSON
    Schema 2020-12 when no explicit `$schema` is provided.
    """

    icons: list[Icon] | None = None
    """Optional set of sized icons that the client can display in a user
    interface (2025-11-25 and later)."""

    annotations: ToolAnnotations | None = None
    """Optional additional tool information.

    Display name precedence order is: title, annotations.title, then name.
    """

    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification's general-fields documentation for notes on
    _meta usage."""


class ListToolsResult(PaginatedResult, CacheableResult):
    """The server's response to a tools/list request from the client."""

    tools: list[Tool]
    """The list of tools the server offers."""


class CallToolRequestParams(InputResponseRequestParams):
    """Parameters for a `tools/call` request."""

    name: str
    """The name of the tool."""

    arguments: dict[str, Any] | None = None
    """Arguments to use for the tool call."""

    task: TaskMetadata | None = None
    """If specified, the caller is requesting task-augmented execution for this request.

    The request will return a CreateTaskResult immediately, and the actual result
    can be retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare
    support for task augmentation of specific request types in their capabilities.

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
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

    # OD-1 alternative: an Unset-sentinel default distinguishing wire-absent from
    # explicit null (needs client and existing-test carve-outs).
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

    On protocol versions through 2025-11-25, servers may send this without any previous
    subscription from the client. On 2026-07-28 sessions, delivery is opt-in: the server
    sends it only if the client requested it via `subscriptions/listen`
    (`SubscriptionFilter.tools_list_changed`).
    """

    method: Literal["notifications/tools/list_changed"] = "notifications/tools/list_changed"
    params: NotificationParams | None = None


LoggingLevel = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
"""The severity of a log message.

These map to syslog message severities, as specified in RFC-5424:
https://datatracker.ietf.org/doc/html/rfc5424#section-6.2.1

The value set is identical in every protocol version (2024-11-05 through 2026-07-28).
Protocol 2026-07-28 deprecates the logging family as a whole (SEP-2577) but keeps it
fully functional for at least twelve months; the level scale itself is unchanged.
"""


# --- Removed in protocol 2026-07-28: logging/setLevel.
# 2026-07-28 sessions opt in to log messages per-request via the
# io.modelcontextprotocol/logLevel _meta key instead.


class SetLevelRequestParams(RequestParams):
    """Parameters for setting the logging level.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    """

    level: LoggingLevel
    """The level of logging that the client wants to receive from the server.

    The server should send all logs at this level and higher (i.e., more severe)
    to the client as notifications/message.
    """


class SetLevelRequest(Request[SetLevelRequestParams, Literal["logging/setLevel"]]):
    """A request from the client to the server, to enable or adjust logging.

    Removed in protocol 2026-07-28; sent/received on sessions negotiating <= 2025-11-25.
    On 2026-07-28 sessions the client opts in to log messages per-request via the
    `io.modelcontextprotocol/logLevel` key in `_meta` instead.
    """

    method: Literal["logging/setLevel"] = "logging/setLevel"
    params: SetLevelRequestParams


class LoggingMessageNotificationParams(NotificationParams):
    """Parameters for a `notifications/message` notification.

    Deprecated as of protocol 2026-07-28 (SEP-2577) but still part of that
    version; fully supported on all earlier protocol versions.
    """

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
    """Notification of a log message passed from server to client.

    On protocol versions through 2025-11-25, the client subscribes via
    `logging/setLevel`; if it never did, the server MAY decide which messages to
    send automatically. On 2026-07-28 sessions the client instead opts in
    per-request via the `io.modelcontextprotocol/logLevel` `_meta` key, and the
    server MUST NOT send this notification for a request without it (a
    session-layer obligation; this type does not validate the send condition).
    Deprecated as of protocol 2026-07-28 (SEP-2577) but still part of that version.
    """

    method: Literal["notifications/message"] = "notifications/message"
    params: LoggingMessageNotificationParams


IncludeContext = Literal["none", "thisServer", "allServers"]
"""Scope of MCP-server context a sampling request asks the client to attach.

The "thisServer" and "allServers" values are deprecated as of protocol
2025-11-25 (SEP-2596); servers SHOULD omit the field or use "none" unless the
client declares the sampling.context capability.
"""


class ModelHint(MCPModel):
    """Hints to use for model selection.

    Keys not declared here are currently left unspecified by the spec and are
    up to the client to interpret.

    Deprecated as of protocol 2026-07-28 (SEP-2577) together with the rest of
    the sampling family; remains in the specification for at least twelve
    months and is still carried by embedded sampling requests on 2026-07-28
    sessions.
    """

    name: str | None = None
    """A hint for a model name.

    The client SHOULD treat this as a substring of a model name; for example:

    - ``claude-3-5-sonnet`` should match ``claude-3-5-sonnet-20241022``
    - ``sonnet`` should match ``claude-3-5-sonnet-20241022``,
      ``claude-3-sonnet-20240229``, etc.
    - ``claude`` should match any Claude model

    The client MAY also map the string to a different provider's model name or
    a different model family, as long as it fills a similar niche; for example:

    - ``gemini-1.5-flash`` could match ``claude-3-haiku-20240307``
    """


class ModelPreferences(MCPModel):
    """The server's preferences for model selection, requested of the client during
    sampling.

    Because LLMs can vary along multiple dimensions, choosing the "best" model is
    rarely straightforward. Different models excel in different areas—some are
    faster but less capable, others are more capable but more expensive, and so
    on. This interface allows servers to express their priorities across multiple
    dimensions to help clients make an appropriate selection for their use case.

    These preferences are always advisory. The client MAY ignore them. It is also
    up to the client to decide how to interpret these preferences and how to
    balance them against other considerations.

    Deprecated as of protocol 2026-07-28 (SEP-2577), along with the rest of the
    sampling family, but remains in the specification for at least twelve months
    and stays fully supported here.
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
    """Controls tool selection behavior for sampling requests.

    Sent by servers as `CreateMessageRequestParams.tool_choice`
    (sampling-with-tools, protocol 2025-11-25 and later). The client MUST
    return an error if it receives the carrying field without having declared
    `ClientCapabilities.sampling.tools`. When the carrying field is absent,
    the default is `{"mode": "auto"}`.
    """

    mode: Literal["auto", "required", "none"] | None = None
    """
    Controls the tool use ability of the model:
    - "auto": Model decides whether to use tools (default)
    - "required": Model MUST use at least one tool before completing
    - "none": Model MUST NOT use any tools
    """


class CreateMessageRequestParams(RequestParams):
    """Parameters for a sampling/createMessage request."""

    messages: list[SamplingMessage]
    """The conversation to sample from."""
    model_preferences: ModelPreferences | None = None
    """
    The server's preferences for which model to select. The client MAY ignore
    these preferences.
    """
    system_prompt: str | None = None
    """
    An optional system prompt the server wants to use for sampling. The client
    MAY modify or omit this prompt.
    """
    include_context: IncludeContext | None = None
    """
    A request to include context from one or more MCP servers (including the
    caller), to be attached to the prompt. The client MAY ignore this request.

    Default is "none". The "thisServer" and "allServers" values are deprecated
    (SEP-2596): servers SHOULD only send them if the client declares the
    sampling.context capability.
    """
    temperature: float | None = None
    """Sampling temperature requested by the server."""
    max_tokens: int
    """
    The requested maximum number of tokens to sample (to prevent runaway
    completions). The client MAY choose to sample fewer tokens than the
    requested maximum.
    """
    stop_sequences: list[str] | None = None
    """Sequences at which the client should stop sampling."""
    metadata: dict[str, Any] | None = None
    """
    Optional metadata to pass through to the LLM provider. The format of this
    metadata is provider-specific.
    """
    tools: list[Tool] | None = None
    """
    Tools that the model may use during generation (protocol 2025-11-25 and
    later). The client MUST return an error if this field is provided but the
    sampling.tools client capability is not declared.
    """
    tool_choice: ToolChoice | None = None
    """
    Controls how the model uses tools (protocol 2025-11-25 and later). The
    client MUST return an error if this field is provided but the
    sampling.tools client capability is not declared. Default is mode="auto".
    """
    task: TaskMetadata | None = None
    """If set, requests task-augmented execution for this request.

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
    """


class CreateMessageRequest(Request[CreateMessageRequestParams, Literal["sampling/createMessage"]]):
    """A request from the server to sample an LLM via the client.

    The client has full discretion over which model to select. The client
    should also inform the user before beginning sampling, to allow them to
    inspect the request (human in the loop) and decide whether to approve it.

    On 2024-11-05 through 2025-11-25 sessions this is a standalone JSON-RPC
    server-to-client request. On 2026-07-28 sessions the same payload is
    instead embedded in InputRequiredResult.input_requests and is never sent
    as a JSON-RPC request. Deprecated as of protocol 2026-07-28 (SEP-2577).
    """

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    params: CreateMessageRequestParams


StopReason = Literal["endTurn", "stopSequence", "maxTokens", "toolUse"] | str
"""The reason why sampling stopped, if known.

Standard values:
- "endTurn": Natural end of the assistant's turn
- "stopSequence": A stop sequence was encountered
- "maxTokens": Maximum token limit was reached
- "toolUse": The model wants to use one or more tools (2025-11-25 and later)

This is an open string to allow for provider-specific stop reasons; every protocol
version models it as an open union.
"""


class CreateMessageResult(Result):
    """The client's response to a sampling/createMessage request from the server.

    This is the backwards-compatible version that returns single content (no arrays).
    Used when the request does not include tools.

    The client should inform the user before returning the sampled message, to allow
    them to inspect the response (human in the loop). On 2026-07-28 sessions this
    payload travels embedded in an ``InputResponses`` map rather than as a top-level
    JSON-RPC result; sampling is deprecated as of 2026-07-28 (SEP-2577) but remains
    in the specification.
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
    """Reference-type discriminator; always "ref/resource"."""
    uri: str
    """The URI or URI template of the resource."""


# PromptReference stays flat on MCPModel even though the schema has it extend
# BaseMetadata since 2025-06-18: inheriting would reorder dump keys
# (type, name) -> (name, title, type), changing emitted bytes for existing
# callers, so `title` is declared directly instead.
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
    """Parameters for a `completion/complete` request."""

    ref: ResourceTemplateReference | PromptReference
    """The prompt or resource-template reference to complete against."""
    argument: CompletionArgument
    """The argument's information."""
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
    """The completion values, with optional total / has-more pagination hints."""


class ListRootsRequest(Request[RequestParams | None, Literal["roots/list"]]):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.

    On protocol versions 2024-11-05 through 2025-11-25 this is a server -> client
    JSON-RPC request. On 2026-07-28 sessions there are no server -> client JSON-RPC
    requests; the same payload travels embedded as an ``InputRequest`` value inside
    ``InputRequiredResult.input_requests``. Deprecated as of protocol version
    2026-07-28 (SEP-2577).
    """

    method: Literal["roots/list"] = "roots/list"
    params: RequestParams | None = None
    """Optional request parameters. Unlike client -> server requests, ``params``
    stays optional on 2026-07-28 (the reserved client ``_meta`` keys do not apply
    to server -> client payloads)."""


class Root(MCPModel):
    """Represents a root directory or file that the server can operate on.

    Deprecated as of protocol 2026-07-28 (SEP-2577) together with the rest of
    the roots family; remains in the specification for at least twelve months
    and is still carried by embedded ``roots/list`` responses on 2026-07-28
    sessions.
    """

    uri: FileUrl
    """The URI identifying the root. This *must* start with ``file://`` for now.

    This restriction may be relaxed in future versions of the protocol to
    allow other URI schemes.
    """
    name: str | None = None
    """An optional name for the root.

    This can be used to provide a human-readable identifier for the root,
    which may be useful for display purposes or for referencing the root in
    other parts of the application.
    """
    meta: Meta | None = Field(alias="_meta", default=None)
    """See the MCP specification's general-fields documentation for notes on
    ``_meta`` usage."""


class ListRootsResult(Result):
    """The client's response to a roots/list request from the server.

    This result contains an array of Root objects, each representing a root
    directory or file that the server can operate on.

    On 2026-07-28 sessions this payload is not a JSON-RPC result: it is carried
    as an embedded input-response value (an ``InputResponses`` map entry) on a
    retried client request, and the roots feature is deprecated (SEP-2577).
    """

    roots: list[Root]
    """The root directories or files the client exposes to the server."""


# --- Removed in protocol 2026-07-28: notifications/roots/list_changed.
# The 2026-07-28 revision has no standalone roots/list request for this
# notification to prompt; embedded roots/list payloads are re-requested per flow.


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
    """Parameters for a `notifications/cancelled` notification."""

    request_id: RequestId | None = None
    """The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same
    direction. Required on the wire for protocol versions <= 2025-06-18;
    optional from 2025-11-25 (where task cancellation uses the `tasks/cancel`
    request, never this field).
    """
    reason: str | None = None
    """An optional string describing the reason for the cancellation.

    This MAY be logged or presented to the user.
    """


class CancelledNotification(Notification[CancelledNotificationParams, Literal["notifications/cancelled"]]):
    """This notification can be sent by either side to indicate that it is cancelling
    a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it
    is always possible that this notification MAY arrive after the request has
    already finished. This notification indicates that the result will be
    unused, so any associated processing SHOULD cease.

    On protocol versions <= 2025-11-25, a client MUST NOT attempt to cancel its
    `initialize` request (the method does not exist at 2026-07-28).
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

Membership is the superset of every supported version's ``ClientRequest`` union;
the 2025-11-25 task requests are deliberately excluded (types-only, never
dispatched). Whether a member is valid on a session's negotiated version is a
dispatch-gate question answered by the per-version method tables in
``mcp.types.wire``, not by this union: inbound parsing stays superset-lenient on
every session.
"""
client_request_adapter = TypeAdapter[ClientRequest](ClientRequest)
"""TypeAdapter for parsing wire request bodies into `ClientRequest`."""


ClientNotification = (
    CancelledNotification | ProgressNotification | InitializedNotification | RootsListChangedNotification
)
"""Notifications sent from the client to the server.

Superset across protocol versions: all four members are valid on every released
version (2024-11-05 through 2025-11-25). On 2026-07-28 sessions only
``CancelledNotification | ProgressNotification`` are valid; whether a member is
valid on a session's negotiated version is a dispatch-gate question answered by
the per-version method tables in ``mcp.types.wire``, not by this alias.
"""
client_notification_adapter = TypeAdapter[ClientNotification](ClientNotification)
"""TypeAdapter for parsing wire notification bodies into `ClientNotification`."""


# Type for elicitation schema - a JSON Schema dict
ElicitRequestedSchema: TypeAlias = dict[str, Any]
"""Schema for elicitation requests.

A restricted subset of JSON Schema: only top-level properties are allowed,
without nesting.
"""


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

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
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

    Sent/received on sessions negotiating 2025-11-25 only; removed in protocol
    2026-07-28 (tasks continue as an extension).
    """


# Union type for elicitation request parameters
ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams
"""Parameters for elicitation requests - either form or URL mode."""


class ElicitRequest(Request[ElicitRequestParams, Literal["elicitation/create"]]):
    """A request from the server to elicit additional information from the user via the client."""

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

Values of the ``InputRequests`` map carried by ``InputRequiredResult.input_requests``
(and, in the tasks extension, by task types such as ``InputRequiredTask``). On
2026-07-28 sessions these embedded payloads replace the standalone server-to-client
JSON-RPC requests of earlier protocol versions; each member's required ``method``
literal is the discriminating tag.
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


# Deferred-annotation completion: InputResponseRequestParams (and its three
# consumers) reference InputResponses, which is only bound above. Explicit
# rebuilds keep model completion at import time rather than first use.
InputResponseRequestParams.model_rebuild()
ReadResourceRequestParams.model_rebuild()
GetPromptRequestParams.model_rebuild()
CallToolRequestParams.model_rebuild()


ClientResult = EmptyResult | CreateMessageResult | CreateMessageResultWithTools | ListRootsResult | ElicitResult
"""Union of result payloads a client can return for a server's standalone request.

Rides the standalone server-to-client request channel (ping, sampling, roots,
elicitation), which exists on 2024-11-05 through 2025-11-25 sessions only; on
2026-07-28 sessions the non-ping payloads travel as ``InputResponses`` map
entries instead of top-level results. Whether a member is valid on a session's
negotiated version is a dispatch-gate question answered by the per-version
method tables in ``mcp.types.wire``, not by this union.
"""
client_result_adapter = TypeAdapter[ClientResult](ClientResult)
"""TypeAdapter for parsing wire result bodies into `ClientResult`."""


ServerRequest = PingRequest | CreateMessageRequest | ListRootsRequest | ElicitRequest
"""Union of standalone JSON-RPC requests a server can send to a client.

Live on 2024-11-05 through 2025-11-25 sessions only: the 2026-07-28 protocol
removes the standalone server-to-client request channel. On 2026-07-28 sessions,
sampling, roots, and elicitation requests are instead embedded in
``InputRequiredResult.input_requests``, and ping is removed entirely, so the
server-request method set for that version is empty.
"""
server_request_adapter = TypeAdapter[ServerRequest](ServerRequest)
"""TypeAdapter for parsing wire request bodies into `ServerRequest`."""


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

Membership is the superset of every supported version's ``ServerNotification``
union; the 2025-11-25 ``TaskStatusNotification`` is deliberately excluded
(types-only, never dispatched). Whether a member is valid on a session's
negotiated version is a dispatch-gate question answered by the per-version
method tables in ``mcp.types.wire``, not by this union: inbound parsing stays
superset-lenient on every session.
"""
server_notification_adapter = TypeAdapter[ServerNotification](ServerNotification)
"""TypeAdapter for parsing wire notification bodies into `ServerNotification`."""


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

Spans all supported protocol versions: ``InitializeResult`` is only valid on
pre-2026-07-28 sessions; ``DiscoverResult`` and ``InputRequiredResult`` only on
2026-07-28 sessions. ``InputRequiredResult`` is placed last: every one of its
fields is optional, so an earlier slot could shadow other members under smart
union resolution. Whether a member is valid on a session's negotiated version
is enforced at the dispatch boundary, not by this union.
"""
server_result_adapter = TypeAdapter[ServerResult](ServerResult)
"""TypeAdapter for parsing wire result bodies into `ServerResult`."""
