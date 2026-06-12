"""Internal wire-shape models for protocol 2025-06-18. Not part of the public API.

Initially generated from schema/2025-06-18/schema.json @ 6d441518de8a9d5adbab0b10a76a667a63f90665 by
``scripts/update_spec_types.py --src`` (datamodel-code-generator
0.57.0), then hand-validated against the pinned schema.
Maintained as ordinary source: edits are permitted, but
``tests/types/test_version_model_parity.py`` pins every definition against the
generated spec oracle for this version — a drifting edit fails CI. Prefer
fixing the generator pass and re-scaffolding over hand-patching.

The models are deliberately closed (``extra="ignore"``) even where the schema
declares an object open to extra fields — see ``mcp.types._wire_base`` for the
rationale. The classes kept open are commented in place.

Models live in this package's ``__init__.py`` so the whole version reads as
one file beside its pinned schema; the package form leaves room for a future
per-family split without import-path churn.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field

from mcp.types._wire_base import OpenWireModel, WireModel


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


class BooleanSchema(WireModel):
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


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


class Context(WireModel):
    """Additional, optional context for completions"""

    arguments: dict[str, str] | None = None
    """
    Previously-resolved variables in a URI template or prompt.
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
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    completion: Completion


Cursor: TypeAlias = str


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
    # rendering verbatim and the parity test pins this annotation separately.
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


class Params7(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class InitializedNotification(WireModel):
    """This notification is sent from the client to the server after initialization has finished."""

    method: Literal["notifications/initialized"]
    params: Params7 | None = None


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
    params: Params7 | None = None


class Params10(WireModel):
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


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
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class Notification(WireModel):
    method: str
    params: NotificationParams | None = None


class NumberSchema(WireModel):
    description: str | None = None
    # Deliberate deviation from the pinned schema.json, which renders these
    # bounds as "integer" — schema.ts types them number (JSON Schema
    # minimum/maximum are numbers; the schema describes number fields too).
    # The float arms follow schema.ts; the generated oracle keeps the
    # rendering verbatim and the parity test pins these annotations
    # separately.
    maximum: int | float | None = None
    minimum: int | float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


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
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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


class PromptListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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
    """See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage."""

    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """
    If specified, the caller is requesting out-of-band progress notifications for this request (as represented by
    notifications/progress). The value of this parameter is an opaque token that will be attached to any subsequent
    notifications. The receiver is not obligated to provide these notifications.
    """


class RequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class Request(WireModel):
    method: str
    params: RequestParams | None = None


RequestId: TypeAlias = str | int


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


class ResourceListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class ResourceListChangedNotification(WireModel):
    """An optional notification from the server to the client, informing it that the list of resources it can read
    from has changed. This may be issued by servers without any previous subscription from the client.
    """

    method: Literal["notifications/resources/list_changed"]
    params: ResourceListChangedNotificationParams | None = None


class ResourceTemplateReference(WireModel):
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
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


Role: TypeAlias = Literal["assistant", "user"]


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


class RootsListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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


class StringSchema(WireModel):
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


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


class InputSchema(WireModel):
    """A JSON Schema object defining the expected parameters for the tool."""

    # Stays open: schema keywords beyond the declared properties ride extra fields.
    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


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


class ToolAnnotations(WireModel):
    """Additional properties describing a Tool to clients.

    NOTE: all properties in ToolAnnotations are **hints**.
    They are not guaranteed to provide a faithful description of
    tool behavior (including descriptive properties like `title`).

    Clients should never make tool use decisions based on ToolAnnotations
    received from untrusted servers.
    """

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    """
    If true, the tool may perform destructive updates to its environment.
    If false, the tool performs only additive updates.

    (This property is meaningful only when `readOnlyHint == false`)

    Default: true
    """
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    """
    If true, calling the tool repeatedly with the same arguments
    will have no additional effect on the its environment.

    (This property is meaningful only when `readOnlyHint == false`)

    Default: false
    """
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    """
    If true, this tool may interact with an "open world" of external
    entities. If false, the tool's domain of interaction is closed.
    For example, the world of a web search tool is open, whereas that
    of a memory tool is not.

    Default: true
    """
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    """
    If true, the tool does not modify its environment.

    Default: false
    """
    title: str | None = None
    """
    A human-readable title for the tool.
    """


class ToolListChangedNotificationParams(WireModel):
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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


EmptyResult: TypeAlias = Result


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


class JSONRPCError(WireModel):
    """A response to a request that indicates an error occurred."""

    error: Error
    id: RequestId
    jsonrpc: Literal["2.0"]


class JSONRPCRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


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
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


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
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    roots: list[Root]


class PingRequestParams(WireModel):
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class PingRequest(WireModel):
    """A ping, issued by either the server or the client, to check that the other party is still alive. The receiver
    must promptly respond, or else may be disconnected.
    """

    method: Literal["ping"]
    params: PingRequestParams | None = None


PrimitiveSchemaDefinition: TypeAlias = StringSchema | NumberSchema | BooleanSchema | EnumSchema


class ProgressNotificationParams(WireModel):
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


class ProgressNotification(WireModel):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


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


ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | LoggingMessageNotification
)


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


JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError


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


ClientResult: TypeAlias = Result | CreateMessageResult | ListRootsResult | ElicitResult


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
