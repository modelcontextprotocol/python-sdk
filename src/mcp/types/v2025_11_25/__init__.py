"""Internal wire-shape models for protocol 2025-11-25. Generated; do not edit.

Regenerate with ``scripts/gen_surface_types.py`` from ``schema/2025-11-25.json``
(sha256 ``4e01628360a2149892eab8f298ceee626d24a58862184eb8ec85d95b8f353e31``)."""
# pyright: reportIncompatibleVariableOverride=false, reportGeneralTypeIssues=false

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.types._wire_base import WireModel
from pydantic import ConfigDict, Field, RootModel


class BaseMetadata(WireModel):
    """
    Base interface for metadata with name (identifier) and title (display name) properties.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    model_config = ConfigDict(
        extra="allow",
    )
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


class Params(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to cancel.
    """


class Elicitation(WireModel):
    """
    Present if the client supports elicitation from the server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    form: dict[str, Any] | None = None
    url: dict[str, Any] | None = None


class Roots(WireModel):
    """
    Present if the client supports listing roots.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether the client supports notifications for changes to the roots list.
    """


class Sampling(WireModel):
    """
    Present if the client supports sampling from an LLM.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Task support for elicitation-related requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    create: dict[str, Any] | None = None
    """
    Whether the client supports task-augmented elicitation/create requests.
    """


class Sampling1(WireModel):
    """
    Task support for sampling-related requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    create_message: Annotated[dict[str, Any] | None, Field(alias="createMessage")] = None
    """
    Whether the client supports task-augmented sampling/createMessage requests.
    """


class Requests(WireModel):
    """
    Specifies which request types can be augmented with tasks.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    elicitation: Elicitation1 | None = None
    """
    Task support for elicitation-related requests.
    """
    sampling: Sampling1 | None = None
    """
    Task support for sampling-related requests.
    """


class Tasks(WireModel):
    """
    Present if the client supports task-augmented requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ClientCapabilities(WireModel):
    """
    Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a closed set: any client can define its own, additional capabilities.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class Argument(WireModel):
    """
    The argument's information
    """

    model_config = ConfigDict(
        extra="allow",
    )
    name: str
    """
    The name of the argument
    """
    value: str
    """
    The value of the argument to use for completion matching.
    """


class Context(WireModel):
    """
    Additional, optional context for completions
    """

    model_config = ConfigDict(
        extra="allow",
    )
    arguments: dict[str, str] | None = None
    """
    Previously-resolved variables in a URI template or prompt.
    """


class Completion(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    has_more: Annotated[bool | None, Field(alias="hasMore")] = None
    """
    Indicates whether there are additional completion options beyond those provided in the current response, even if the exact total is unknown.
    """
    total: int | None = None
    """
    The total number of completion options available. This can exceed the number of values actually sent in the response.
    """
    values: list[str]
    """
    An array of completion values. Must not exceed 100 items.
    """


class CompleteResult(WireModel):
    """
    The server's response to a completion/complete request
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    completion: Completion


class Cursor(RootModel[str]):
    root: str
    """
    An opaque token used to represent a cursor for pagination.
    """


class ElicitResult(WireModel):
    """
    The client's response to an elicitation request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    content: dict[str, list[str] | str | float | bool] | None = None
    """
    The submitted form data, only present when action is "accept" and mode was "form".
    Contains values matching the requested schema.
    Omitted for out-of-band mode responses.
    """


class Params1(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    elicitation_id: Annotated[str, Field(alias="elicitationId")]
    """
    The ID of the elicitation that completed.
    """


class ElicitationCompleteNotification(WireModel):
    """
    An optional notification from the server to the client, informing it of a completion of a out-of-band elicitation request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/elicitation/complete"]
    params: Params1


class Error(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: int
    """
    The error type that occurred.
    """
    data: Any | None = None
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error information, nested errors etc.).
    """
    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single sentence.
    """


class Params2(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to retrieve results for.
    """


class GetTaskPayloadResult(WireModel):
    """
    The response to a tasks/result request.
    The structure matches the result type of the original request.
    For example, a tools/call task would return the CallToolResult structure.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """


class Params3(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier to query.
    """


class Icon(WireModel):
    """
    An optionally-sized icon that can be displayed in a user interface.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Base interface to add `icons` property.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class Implementation(WireModel):
    """
    Describes the MCP implementation.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    """
    A notification which does not expect a response.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class LegacyTitledEnumSchema(WireModel):
    """
    Use TitledSingleSelectEnumSchema instead.
    This interface will be removed in a future version.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class LoggingLevel(
    RootModel[
        Literal[
            "alert",
            "critical",
            "debug",
            "emergency",
            "error",
            "info",
            "notice",
            "warning",
        ]
    ]
):
    root: Literal["alert", "critical", "debug", "emergency", "error", "info", "notice", "warning"]
    """
    The severity of a log message.

    These map to syslog message severities, as specified in RFC-5424:
    https://datatracker.ietf.org/doc/html/rfc5424#section-6.2.1
    """


class LoggingMessageNotificationParams(WireModel):
    """
    Parameters for a `notifications/message` notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ModelHint(WireModel):
    """
    Hints to use for model selection.

    Keys not declared here are currently left unspecified by the spec and are up
    to the client to interpret.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    name: str | None = None
    """
    A hint for a model name.

    The client SHOULD treat this as a substring of a model name; for example:
     - `claude-3-5-sonnet` should match `claude-3-5-sonnet-20241022`
     - `sonnet` should match `claude-3-5-sonnet-20241022`, `claude-3-sonnet-20240229`, etc.
     - `claude` should match any Claude model

    The client MAY also map the string to a different provider's model name or a different model family, as long as it fills a similar niche; for example:
     - `gemini-1.5-flash` could match `claude-3-haiku-20240307`
    """


class ModelPreferences(WireModel):
    """
    The server's preferences for model selection, requested of the client during sampling.

    Because LLMs can vary along multiple dimensions, choosing the "best" model is
    rarely straightforward.  Different models excel in different areas—some are
    faster but less capable, others are more capable but more expensive, and so
    on. This interface allows servers to express their priorities across multiple
    dimensions to help clients make an appropriate selection for their use case.

    These preferences are always advisory. The client MAY ignore them. It is also
    up to the client to decide how to interpret these preferences and how to
    balance them against other considerations.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class Notification(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    method: str
    params: dict[str, Any] | None = None


class NotificationParams(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """


class NumberSchema(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    default: float | None = None
    description: str | None = None
    maximum: float | None = None
    minimum: float | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class PaginatedResult(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """


class ProgressToken(RootModel[str | int]):
    root: str | int
    """
    A progress token, used to associate progress notifications with the original request.
    """


class PromptArgument(WireModel):
    """
    Describes an argument that a prompt can accept.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = None
    """
    A human-readable description of the argument.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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


class PromptListChangedNotification(WireModel):
    """
    An optional notification from the server to the client, informing it that the list of prompts it offers has changed. This may be issued by servers without any previous subscription from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/prompts/list_changed"]
    params: NotificationParams | None = None


class PromptReference(WireModel):
    """
    Identifies a prompt.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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


class Meta(WireModel):
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """
    If specified, the caller is requesting out-of-band progress notifications for this request (as represented by notifications/progress). The value of this parameter is an opaque token that will be attached to any subsequent notifications. The receiver is not obligated to provide these notifications.
    """


class ReadResourceRequestParams(WireModel):
    """
    Parameters for a `resources/read` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class RelatedTaskMetadata(WireModel):
    """
    Metadata for associating messages with a task.
    Include this in the `_meta` field under the key `io.modelcontextprotocol/related-task`.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    """
    The task identifier this message is associated with.
    """


class Request(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    method: str
    params: dict[str, Any] | None = None


class RequestId(RootModel[str | int]):
    root: str | int
    """
    A uniquely identifying ID for a request in JSON-RPC.
    """


class RequestParams(WireModel):
    """
    Common params for any request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """


class ResourceContents(WireModel):
    """
    The contents of a specific resource or sub-resource.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: str
    """
    The URI of this resource.
    """


class ResourceListChangedNotification(WireModel):
    """
    An optional notification from the server to the client, informing it that the list of resources it can read from has changed. This may be issued by servers without any previous subscription from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/list_changed"]
    params: NotificationParams | None = None


class ResourceRequestParams(WireModel):
    """
    Common parameters when working with resources.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class ResourceTemplateReference(WireModel):
    """
    A reference to a resource or resource template definition.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    type: Literal["ref/resource"]
    uri: str
    """
    The URI or URI template of the resource.
    """


class ResourceUpdatedNotificationParams(WireModel):
    """
    Parameters for a `notifications/resources/updated` notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource that has been updated. This might be a sub-resource of the one that the client actually subscribed to.
    """


class Result(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """


class Role(RootModel[Literal["assistant", "user"]]):
    root: Literal["assistant", "user"]
    """
    The sender or recipient of messages and data in a conversation.
    """


class Root(WireModel):
    """
    Represents a root directory or file that the server can operate on.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class RootsListChangedNotification(WireModel):
    """
    A notification from the client to the server, informing it that the list of roots has changed.
    This notification should be sent whenever the client adds, removes, or modifies any root.
    The server should then request an updated list of roots using the ListRootsRequest.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/roots/list_changed"]
    params: NotificationParams | None = None


class Prompts(WireModel):
    """
    Present if the server offers any prompt templates.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the prompt list.
    """


class Resources(WireModel):
    """
    Present if the server offers any resources to read.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the resource list.
    """
    subscribe: bool | None = None
    """
    Whether this server supports subscribing to resource updates.
    """


class Tools(WireModel):
    """
    Task support for tool-related requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    call: dict[str, Any] | None = None
    """
    Whether the server supports task-augmented tools/call requests.
    """


class Requests1(WireModel):
    """
    Specifies which request types can be augmented with tasks.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    tools: Tools | None = None
    """
    Task support for tool-related requests.
    """


class Tasks1(WireModel):
    """
    Present if the server supports task-augmented requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Present if the server offers any tools to call.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the tool list.
    """


class ServerCapabilities(WireModel):
    """
    Capabilities that a server may support. Known capabilities are defined here, in this schema, but this is not a closed set: any server can define its own, additional capabilities.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Parameters for a `logging/setLevel` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    level: LoggingLevel
    """
    The level of logging that the client wants to receive from the server. The server should send all logs at this level and higher (i.e., more severe) to the client as notifications/message.
    """


class StringSchema(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    default: str | None = None
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class SubscribeRequestParams(WireModel):
    """
    Parameters for a `resources/subscribe` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class TaskMetadata(WireModel):
    """
    Metadata for augmenting a request with task execution.
    Include this in the `task` field of the request parameters.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    ttl: int | None = None
    """
    Requested duration in milliseconds to retain task from creation.
    """


class TaskStatus(RootModel[Literal["cancelled", "completed", "failed", "input_required", "working"]]):
    root: Literal["cancelled", "completed", "failed", "input_required", "working"]
    """
    The status of a task.
    """


class TextResourceContents(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class AnyOfItem(WireModel):
    model_config = ConfigDict(
        extra="allow",
    )
    const: str
    """
    The constant enum value.
    """
    title: str
    """
    Display title for this option.
    """


class Items(WireModel):
    """
    Schema for array items with enum options and display labels.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    any_of: Annotated[list[AnyOfItem], Field(alias="anyOf")]
    """
    Array of enum options with values and display labels.
    """


class TitledMultiSelectEnumSchema(WireModel):
    """
    Schema for multiple-selection enumeration with display titles for each option.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    model_config = ConfigDict(
        extra="allow",
    )
    const: str
    """
    The enum value.
    """
    title: str
    """
    Display label for this option.
    """


class TitledSingleSelectEnumSchema(WireModel):
    """
    Schema for single-selection enumeration with display titles for each option.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class InputSchema(WireModel):
    """
    A JSON Schema object defining the expected parameters for the tool.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class OutputSchema(WireModel):
    """
    An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult.

    Defaults to JSON Schema 2020-12 when no explicit $schema is provided.
    Currently restricted to type: "object" at the root level.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class ToolAnnotations(WireModel):
    """
    Additional properties describing a Tool to clients.

    NOTE: all properties in ToolAnnotations are **hints**.
    They are not guaranteed to provide a faithful description of
    tool behavior (including descriptive properties like `title`).

    Clients should never make tool use decisions based on ToolAnnotations
    received from untrusted servers.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    will have no additional effect on its environment.

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


class ToolChoice(WireModel):
    """
    Controls tool selection behavior for sampling requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    mode: Literal["auto", "none", "required"] | None = None
    """
    Controls the tool use ability of the model:
    - "auto": Model decides whether to use tools (default)
    - "required": Model MUST use at least one tool before completing
    - "none": Model MUST NOT use any tools
    """


class ToolExecution(WireModel):
    """
    Execution-related properties for a tool.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ToolListChangedNotification(WireModel):
    """
    An optional notification from the server to the client, informing it that the list of tools it offers has changed. This may be issued by servers without any previous subscription from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tools/list_changed"]
    params: NotificationParams | None = None


class ToolUseContent(WireModel):
    """
    A request from the assistant to call a tool.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class UnsubscribeRequestParams(WireModel):
    """
    Parameters for a `resources/unsubscribe` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    uri: str
    """
    The URI of the resource. The URI can use any protocol; it is up to the server how to interpret it.
    """


class Items1(WireModel):
    """
    Schema for the array items.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    enum: list[str]
    """
    Array of enum values to choose from.
    """
    type: Literal["string"]


class UntitledMultiSelectEnumSchema(WireModel):
    """
    Schema for multiple-selection enumeration without display titles for options.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Schema for single-selection enumeration without display titles for options.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class Annotations(WireModel):
    """
    Optional annotations for the client. The client can use annotations to inform how objects are used or displayed
    """

    model_config = ConfigDict(
        extra="allow",
    )
    audience: list[Role] | None = None
    """
    Describes who the intended audience of this object or data is.

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
    """
    Audio provided to or from an LLM.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class CallToolRequestParams(WireModel):
    """
    Parameters for a `tools/call` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class CancelTaskRequest(WireModel):
    """
    A request to cancel a task.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/cancel"]
    params: Params


class CancelledNotificationParams(WireModel):
    """
    Parameters for a `notifications/cancelled` notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Parameters for a `completion/complete` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ElicitRequestURLParams(WireModel):
    """
    The parameters for a request to elicit information from the user via a URL in the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class EmbeddedResource(WireModel):
    """
    The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    resource: TextResourceContents | BlobResourceContents
    type: Literal["resource"]


class EmptyResult(RootModel[Result]):
    root: Result


class EnumSchema(
    RootModel[
        UntitledSingleSelectEnumSchema
        | TitledSingleSelectEnumSchema
        | UntitledMultiSelectEnumSchema
        | TitledMultiSelectEnumSchema
        | LegacyTitledEnumSchema
    ]
):
    root: (
        UntitledSingleSelectEnumSchema
        | TitledSingleSelectEnumSchema
        | UntitledMultiSelectEnumSchema
        | TitledMultiSelectEnumSchema
        | LegacyTitledEnumSchema
    )


class GetPromptRequestParams(WireModel):
    """
    Parameters for a `prompts/get` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class GetTaskPayloadRequest(WireModel):
    """
    A request to retrieve the result of a completed task.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/result"]
    params: Params2


class GetTaskRequest(WireModel):
    """
    A request to retrieve the state of a task.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/get"]
    params: Params3


class ImageContent(WireModel):
    """
    An image provided to or from an LLM.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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


class InitializeRequestParams(WireModel):
    """
    Parameters for an `initialize` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The latest version of the Model Context Protocol that the client supports. The client MAY decide to support older versions as well.
    """


class InitializeResult(WireModel):
    """
    After receiving an initialize request from the client, the server sends this response.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    capabilities: ServerCapabilities
    instructions: str | None = None
    """
    Instructions describing how to use the server and its features.

    This can be used by clients to improve the LLM's understanding of available tools, resources, etc. It can be thought of like a "hint" to the model. For example, this information MAY be added to the system prompt.
    """
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The version of the Model Context Protocol that the server wants to use. This may not match the version that the client requested. If the client cannot support this version, it MUST disconnect.
    """
    server_info: Annotated[Implementation, Field(alias="serverInfo")]


class InitializedNotification(WireModel):
    """
    This notification is sent from the client to the server after initialization has finished.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/initialized"]
    params: NotificationParams | None = None


class JSONRPCErrorResponse(WireModel):
    """
    A response to a request that indicates an error occurred.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    error: Error
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class JSONRPCRequest(WireModel):
    """
    A request that expects a response.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResultResponse(WireModel):
    """
    A successful (non-error) response to a request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class ListRootsRequest(WireModel):
    """
    Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["roots/list"]
    params: RequestParams | None = None


class ListRootsResult(WireModel):
    """
    The client's response to a roots/list request from the server.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    roots: list[Root]


class LoggingMessageNotification(WireModel):
    """
    JSONRPCNotification of a log message passed from server to client. If no logging/setLevel request has been sent from the client, the server MAY decide which messages to send automatically.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/message"]
    params: LoggingMessageNotificationParams


class MultiSelectEnumSchema(RootModel[UntitledMultiSelectEnumSchema | TitledMultiSelectEnumSchema]):
    root: UntitledMultiSelectEnumSchema | TitledMultiSelectEnumSchema


class PaginatedRequestParams(WireModel):
    """
    Common parameters for paginated requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    A ping, issued by either the server or the client, to check that the other party is still alive. The receiver must promptly respond, or else may be disconnected.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["ping"]
    params: RequestParams | None = None


class PrimitiveSchemaDefinition(
    RootModel[
        StringSchema
        | NumberSchema
        | BooleanSchema
        | UntitledSingleSelectEnumSchema
        | TitledSingleSelectEnumSchema
        | UntitledMultiSelectEnumSchema
        | TitledMultiSelectEnumSchema
        | LegacyTitledEnumSchema
    ]
):
    root: (
        StringSchema
        | NumberSchema
        | BooleanSchema
        | UntitledSingleSelectEnumSchema
        | TitledSingleSelectEnumSchema
        | UntitledMultiSelectEnumSchema
        | TitledMultiSelectEnumSchema
        | LegacyTitledEnumSchema
    )
    """
    Restricted schema definitions that only allow primitive types
    without nested objects or arrays.
    """


class ProgressNotificationParams(WireModel):
    """
    Parameters for a `notifications/progress` notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    The progress token which was given in the initial request, used to associate this notification with the request that is proceeding.
    """
    total: float | None = None
    """
    Total number of items to process (or total progress required), if known.
    """


class Prompt(WireModel):
    """
    A prompt or prompt template that the server offers.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    """
    Sent from the client to the server, to read a specific resource URI.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/read"]
    params: ReadResourceRequestParams


class ReadResourceResult(WireModel):
    """
    The server's response to a resources/read request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    contents: list[TextResourceContents | BlobResourceContents]


class Resource(WireModel):
    """
    A known resource that the server is capable of reading.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    """
    A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    """
    A template description for resources available on the server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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
    The MIME type for all resources that match this template. This should only be included if all resources matching this template have the same type.
    """
    name: str
    """
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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
    """
    A notification from the server to the client, informing it that a resource has changed and may need to be read again. This should only be sent if the client previously sent a resources/subscribe request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/resources/updated"]
    params: ResourceUpdatedNotificationParams


class SetLevelRequest(WireModel):
    """
    A request from the client to the server, to enable or adjust logging.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["logging/setLevel"]
    params: SetLevelRequestParams


class SingleSelectEnumSchema(RootModel[UntitledSingleSelectEnumSchema | TitledSingleSelectEnumSchema]):
    root: UntitledSingleSelectEnumSchema | TitledSingleSelectEnumSchema


class SubscribeRequest(WireModel):
    """
    Sent from the client to request resources/updated notifications from the server whenever a particular resource changes.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/subscribe"]
    params: SubscribeRequestParams


class Task(WireModel):
    """
    Data associated with a task.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Common params for any task-augmented request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class TaskStatusNotificationParams(NotificationParams, Task):
    """
    Parameters for a `notifications/tasks/status` notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )


class TextContent(WireModel):
    """
    Text provided to or from an LLM.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
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
    """
    Definition for a tool the client can call.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available tools. It can be thought of like a "hint" to the model.
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
    Intended for programmatic or logical use, but used as a display name in past specs or fallback (if title isn't present).
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


class Data(WireModel):
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error information, nested errors etc.).
    """

    model_config = ConfigDict(
        extra="allow",
    )
    elicitations: list[ElicitRequestURLParams]


class Error1(Error):
    model_config = ConfigDict(
        extra="allow",
    )
    code: Literal[-32042]
    """
    The error type that occurred.
    """
    data: Data
    """
    Additional information about the error. The value of this member is defined by the sender (e.g. detailed error information, nested errors etc.).
    """


class URLElicitationRequiredError(WireModel):
    """
    An error response that indicates that the server requires the client to provide additional information via an elicitation request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    error: Error1
    id: RequestId | None = None
    jsonrpc: Literal["2.0"]


class UnsubscribeRequest(WireModel):
    """
    Sent from the client to request cancellation of resources/updated notifications from the server. This should follow a previous resources/subscribe request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/unsubscribe"]
    params: UnsubscribeRequestParams


class CallToolRequest(WireModel):
    """
    Used by the client to invoke a tool provided by the server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/call"]
    params: CallToolRequestParams


class CancelTaskResult(Result, Task):
    """
    The response to a tasks/cancel request.
    """

    model_config = ConfigDict(
        extra="allow",
    )


class CancelledNotification(WireModel):
    """
    This notification can be sent by either side to indicate that it is cancelling a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it is always possible that this notification MAY arrive after the request has already finished.

    This notification indicates that the result will be unused, so any associated processing SHOULD cease.

    A client MUST NOT attempt to cancel its `initialize` request.

    For task cancellation, use the `tasks/cancel` request instead of this notification.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/cancelled"]
    params: CancelledNotificationParams


class CompleteRequest(WireModel):
    """
    A request from the client to the server, to ask for completion options.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["completion/complete"]
    params: CompleteRequestParams


class ContentBlock(RootModel[TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource]):
    root: TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource


class CreateTaskResult(WireModel):
    """
    A response to a task-augmented request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    task: Task


class RequestedSchema(WireModel):
    """
    A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    schema_: Annotated[str | None, Field(alias="$schema")] = None
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class ElicitRequestFormParams(WireModel):
    """
    The parameters for a request to elicit non-sensitive information from the user via a form in the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ElicitRequestParams(RootModel[ElicitRequestURLParams | ElicitRequestFormParams]):
    root: ElicitRequestURLParams | ElicitRequestFormParams
    """
    The parameters for a request to elicit additional information from the user via the client.
    """


class GetPromptRequest(WireModel):
    """
    Used by the client to get a prompt provided by the server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/get"]
    params: GetPromptRequestParams


class GetTaskResult(Result, Task):
    """
    The response to a tasks/get request.
    """

    model_config = ConfigDict(
        extra="allow",
    )


class InitializeRequest(WireModel):
    """
    This request is sent from the client to the server when it first connects, asking it to begin initialization.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["initialize"]
    params: InitializeRequestParams


class JSONRPCMessage(RootModel[JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse]):
    root: JSONRPCRequest | JSONRPCNotification | JSONRPCResultResponse | JSONRPCErrorResponse
    """
    Refers to any valid JSON-RPC object that can be decoded off the wire, or encoded to be sent.
    """


class JSONRPCResponse(RootModel[JSONRPCResultResponse | JSONRPCErrorResponse]):
    root: JSONRPCResultResponse | JSONRPCErrorResponse
    """
    A response to a request, containing either the result or error.
    """


class ListPromptsRequest(WireModel):
    """
    Sent from the client to request a list of prompts and prompt templates the server has.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["prompts/list"]
    params: PaginatedRequestParams | None = None


class ListPromptsResult(WireModel):
    """
    The server's response to a prompts/list request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Sent from the client to request a list of resource templates the server has.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/templates/list"]
    params: PaginatedRequestParams | None = None


class ListResourceTemplatesResult(WireModel):
    """
    The server's response to a resources/templates/list request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Sent from the client to request a list of resources the server has.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["resources/list"]
    params: PaginatedRequestParams | None = None


class ListResourcesResult(WireModel):
    """
    The server's response to a resources/list request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ListTasksRequest(WireModel):
    """
    A request to retrieve a list of tasks.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tasks/list"]
    params: PaginatedRequestParams | None = None


class ListTasksResult(WireModel):
    """
    The response to a tasks/list request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ListToolsRequest(WireModel):
    """
    Sent from the client to request a list of tools the server has.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["tools/list"]
    params: PaginatedRequestParams | None = None


class ListToolsResult(WireModel):
    """
    The server's response to a tools/list request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: PaginatedRequestParams | None = None


class ProgressNotification(WireModel):
    """
    An out-of-band notification used to inform the receiver of a progress update for a long-running request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/progress"]
    params: ProgressNotificationParams


class PromptMessage(WireModel):
    """
    Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    content: ContentBlock
    role: Role


class TaskStatusNotification(WireModel):
    """
    An optional notification from the receiver to the requestor, informing them that a task's status has changed. Receivers are not required to send these notifications.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tasks/status"]
    params: TaskStatusNotificationParams


class ToolResultContent(WireModel):
    """
    The result of a tool use, provided by the user back to the assistant.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
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


class CallToolResult(WireModel):
    """
    The server's response to a tool call.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
    """
    An optional JSON object that represents the structured result of the tool call.
    """


class ClientNotification(
    RootModel[
        CancelledNotification
        | InitializedNotification
        | ProgressNotification
        | TaskStatusNotification
        | RootsListChangedNotification
    ]
):
    root: (
        CancelledNotification
        | InitializedNotification
        | ProgressNotification
        | TaskStatusNotification
        | RootsListChangedNotification
    )


class ClientRequest(
    RootModel[
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
    ]
):
    root: (
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
    """
    A request from the server to elicit additional information from the user via the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["elicitation/create"]
    params: ElicitRequestParams


class GetPromptResult(WireModel):
    """
    The server's response to a prompts/get request from the client.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-11-25/basic/index#meta) for notes on `_meta` usage.
    """
    description: str | None = None
    """
    An optional description for the prompt.
    """
    messages: list[PromptMessage]


class SamplingMessageContentBlock(
    RootModel[TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent]
):
    root: TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent


class ServerNotification(
    RootModel[
        CancelledNotification
        | ProgressNotification
        | ResourceListChangedNotification
        | ResourceUpdatedNotification
        | PromptListChangedNotification
        | ToolListChangedNotification
        | TaskStatusNotification
        | LoggingMessageNotification
        | ElicitationCompleteNotification
    ]
):
    root: (
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


class ServerResult(
    RootModel[
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
    ]
):
    root: (
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
    """
    The client's response to a sampling/createMessage request from the server.
    The client should inform the user before returning the sampled message, to allow them
    to inspect the response (human in the loop) and decide whether to allow the server to see it.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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
    """
    Describes a message issued to or received from an LLM API.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ClientResult(
    RootModel[
        Result
        | GetTaskResult
        | GetTaskPayloadResult
        | CancelTaskResult
        | ListTasksResult
        | CreateMessageResult
        | ListRootsResult
        | ElicitResult
    ]
):
    root: (
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
    """
    Parameters for a `sampling/createMessage` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    Default is "none". Values "thisServer" and "allServers" are soft-deprecated. Servers SHOULD only use these values if the client
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
    """
    A request from the server to sample an LLM via the client. The client has full discretion over which model to select. The client should also inform the user before beginning sampling, to allow them to inspect the request (human in the loop) and decide whether to approve it.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: Literal["sampling/createMessage"]
    params: CreateMessageRequestParams


class ServerRequest(
    RootModel[
        PingRequest
        | GetTaskRequest
        | GetTaskPayloadRequest
        | CancelTaskRequest
        | ListTasksRequest
        | CreateMessageRequest
        | ListRootsRequest
        | ElicitRequest
    ]
):
    root: (
        PingRequest
        | GetTaskRequest
        | GetTaskPayloadRequest
        | CancelTaskRequest
        | ListTasksRequest
        | CreateMessageRequest
        | ListRootsRequest
        | ElicitRequest
    )
