# GENERATED FILE — DO NOT EDIT.
# Source: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/6d441518de8a9d5adbab0b10a76a667a63f90665/schema/2025-06-18/schema.json
# Protocol version: 2025-06-18   Generator: datamodel-code-generator 0.57.0
# Regenerate: uv run --frozen python scripts/update_spec_types.py 2025-06-18 [--sha <new-sha>]
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import AnyUrl, Base64Str, ConfigDict, Field

from tests.spec_oracles._base import OracleModel


class BaseMetadata(OracleModel):
    """Base interface for metadata with name (identifier) and title (display name) properties."""

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


class BlobResourceContents(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    blob: Base64Str
    """
    A base64-encoded string representing the binary data of the item.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: AnyUrl
    """
    The URI of this resource.
    """


class BooleanSchema(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    default: bool | None = None
    description: str | None = None
    title: str | None = None
    type: Literal["boolean"]


class Params(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    arguments: dict[str, Any] | None = None
    name: str


class CallToolRequest(OracleModel):
    """Used by the client to invoke a tool provided by the server."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["tools/call"]
    params: Params


class Roots(OracleModel):
    """Present if the client supports listing roots."""

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether the client supports notifications for changes to the roots list.
    """


class ClientCapabilities(OracleModel):
    """Capabilities a client may support. Known capabilities are defined here, in this schema, but this is not a closed set: any client can define its own, additional capabilities."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class Argument(OracleModel):
    """The argument's information"""

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


class Context(OracleModel):
    """Additional, optional context for completions"""

    model_config = ConfigDict(
        extra="allow",
    )
    arguments: dict[str, str] | None = None
    """
    Previously-resolved variables in a URI template or prompt.
    """


class Completion(OracleModel):
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


class CompleteResult(OracleModel):
    """The server's response to a completion/complete request"""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    completion: Completion


Cursor: TypeAlias = str


class ElicitResult(OracleModel):
    """The client's response to an elicitation request."""

    model_config = ConfigDict(
        extra="allow",
    )
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
    content: dict[str, str | int | bool] | None = None
    """
    The submitted form data, only present when action is "accept".
    Contains values matching the requested schema.
    """


class EnumSchema(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = None
    enum: list[str]
    enum_names: Annotated[list[str] | None, Field(alias="enumNames")] = None
    title: str | None = None
    type: Literal["string"]


class Params5(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    arguments: dict[str, str] | None = None
    """
    Arguments to use for templating the prompt.
    """
    name: str
    """
    The name of the prompt or prompt template.
    """


class GetPromptRequest(OracleModel):
    """Used by the client to get a prompt provided by the server."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["prompts/get"]
    params: Params5


class Implementation(OracleModel):
    """Describes the name and version of an MCP implementation, with an optional title for UI representation."""

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
    version: str


class Params6(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]
    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    """
    The latest version of the Model Context Protocol that the client supports. The client MAY decide to support older versions as well.
    """


class InitializeRequest(OracleModel):
    """This request is sent from the client to the server when it first connects, asking it to begin initialization."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["initialize"]
    params: Params6


class Params7(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class InitializedNotification(OracleModel):
    """This notification is sent from the client to the server after initialization has finished."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/initialized"]
    params: Params7 | None = None


class Error(OracleModel):
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


class JSONRPCNotification(OracleModel):
    """A notification which does not expect a response."""

    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: str
    params: Params7 | None = None


class Params10(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class ListPromptsRequest(OracleModel):
    """Sent from the client to request a list of prompts and prompt templates the server has."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["prompts/list"]
    params: Params10 | None = None


class ListResourceTemplatesRequest(OracleModel):
    """Sent from the client to request a list of resource templates the server has."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["resources/templates/list"]
    params: Params10 | None = None


class ListResourcesRequest(OracleModel):
    """Sent from the client to request a list of resources the server has."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["resources/list"]
    params: Params10 | None = None


class ListToolsRequest(OracleModel):
    """Sent from the client to request a list of tools the server has."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["tools/list"]
    params: Params10 | None = None


LoggingLevel: TypeAlias = Literal["alert", "critical", "debug", "emergency", "error", "info", "notice", "warning"]


class Params15(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
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


class LoggingMessageNotification(OracleModel):
    """Notification of a log message passed from server to client. If no logging/setLevel request has been sent from the client, the server MAY decide which messages to send automatically."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/message"]
    params: Params15


class ModelHint(OracleModel):
    """Hints to use for model selection.

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


class ModelPreferences(OracleModel):
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


class Params16(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class Notification(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    method: str
    params: Params16 | None = None


class NumberSchema(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = None
    maximum: int | None = None
    minimum: int | None = None
    title: str | None = None
    type: Literal["integer", "number"]


class Params17(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    cursor: str | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class PaginatedRequest(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    method: str
    params: Params17 | None = None


class PaginatedResult(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
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


class PromptArgument(OracleModel):
    """Describes an argument that a prompt can accept."""

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


class Params20(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class PromptListChangedNotification(OracleModel):
    """An optional notification from the server to the client, informing it that the list of prompts it offers has changed. This may be issued by servers without any previous subscription from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/prompts/list_changed"]
    params: Params20 | None = None


class PromptReference(OracleModel):
    """Identifies a prompt."""

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


class Params21(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    uri: AnyUrl
    """
    The URI of the resource to read. The URI can use any protocol; it is up to the server how to interpret it.
    """


class ReadResourceRequest(OracleModel):
    """Sent from the client to the server, to read a specific resource URI."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["resources/read"]
    params: Params21


class Meta(OracleModel):
    """See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage."""

    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None
    """
    If specified, the caller is requesting out-of-band progress notifications for this request (as represented by notifications/progress). The value of this parameter is an opaque token that will be attached to any subsequent notifications. The receiver is not obligated to provide these notifications.
    """


class Params22(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class Request(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    method: str
    params: Params22 | None = None


RequestId: TypeAlias = str | int


class ResourceContents(OracleModel):
    """The contents of a specific resource or sub-resource."""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    """
    The MIME type of this resource, if known.
    """
    uri: AnyUrl
    """
    The URI of this resource.
    """


class Params23(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class ResourceListChangedNotification(OracleModel):
    """An optional notification from the server to the client, informing it that the list of resources it can read from has changed. This may be issued by servers without any previous subscription from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/resources/list_changed"]
    params: Params23 | None = None


class ResourceTemplateReference(OracleModel):
    """A reference to a resource or resource template definition."""

    model_config = ConfigDict(
        extra="allow",
    )
    type: Literal["ref/resource"]
    uri: str
    """
    The URI or URI template of the resource.
    """


class Params24(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    uri: AnyUrl
    """
    The URI of the resource that has been updated. This might be a sub-resource of the one that the client actually subscribed to.
    """


class ResourceUpdatedNotification(OracleModel):
    """A notification from the server to the client, informing it that a resource has changed and may need to be read again. This should only be sent if the client previously sent a resources/subscribe request."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/resources/updated"]
    params: Params24


class Result(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


Role: TypeAlias = Literal["assistant", "user"]


class Root(OracleModel):
    """Represents a root directory or file that the server can operate on."""

    model_config = ConfigDict(
        extra="allow",
    )
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
    uri: AnyUrl
    """
    The URI identifying the root. This *must* start with file:// for now.
    This restriction may be relaxed in future versions of the protocol to allow
    other URI schemes.
    """


class Params25(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class RootsListChangedNotification(OracleModel):
    """A notification from the client to the server, informing it that the list of roots has changed.
    This notification should be sent whenever the client adds, removes, or modifies any root.
    The server should then request an updated list of roots using the ListRootsRequest.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/roots/list_changed"]
    params: Params25 | None = None


class Prompts(OracleModel):
    """Present if the server offers any prompt templates."""

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the prompt list.
    """


class Resources(OracleModel):
    """Present if the server offers any resources to read."""

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


class Tools(OracleModel):
    """Present if the server offers any tools to call."""

    model_config = ConfigDict(
        extra="allow",
    )
    list_changed: Annotated[bool | None, Field(alias="listChanged")] = None
    """
    Whether this server supports notifications for changes to the tool list.
    """


class ServerCapabilities(OracleModel):
    """Capabilities that a server may support. Known capabilities are defined here, in this schema, but this is not a closed set: any server can define its own, additional capabilities."""

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
    tools: Tools | None = None
    """
    Present if the server offers any tools to call.
    """


class Params26(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    level: LoggingLevel
    """
    The level of logging that the client wants to receive from the server. The server should send all logs at this level and higher (i.e., more severe) to the client as notifications/message.
    """


class SetLevelRequest(OracleModel):
    """A request from the client to the server, to enable or adjust logging."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["logging/setLevel"]
    params: Params26


class StringSchema(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    description: str | None = None
    format: Literal["date", "date-time", "email", "uri"] | None = None
    max_length: Annotated[int | None, Field(alias="maxLength")] = None
    min_length: Annotated[int | None, Field(alias="minLength")] = None
    title: str | None = None
    type: Literal["string"]


class Params27(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    uri: AnyUrl
    """
    The URI of the resource to subscribe to. The URI can use any protocol; it is up to the server how to interpret it.
    """


class SubscribeRequest(OracleModel):
    """Sent from the client to request resources/updated notifications from the server whenever a particular resource changes."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["resources/subscribe"]
    params: Params27


class TextResourceContents(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
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
    uri: AnyUrl
    """
    The URI of this resource.
    """


class InputSchema(OracleModel):
    """A JSON Schema object defining the expected parameters for the tool."""

    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class OutputSchema(OracleModel):
    """An optional JSON Schema object defining the structure of the tool's output returned in
    the structuredContent field of a CallToolResult.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, dict[str, Any]] | None = None
    required: list[str] | None = None
    type: Literal["object"]


class ToolAnnotations(OracleModel):
    """Additional properties describing a Tool to clients.

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


class Params28(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class ToolListChangedNotification(OracleModel):
    """An optional notification from the server to the client, informing it that the list of tools it offers has changed. This may be issued by servers without any previous subscription from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/tools/list_changed"]
    params: Params28 | None = None


class Params29(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    uri: AnyUrl
    """
    The URI of the resource to unsubscribe from.
    """


class UnsubscribeRequest(OracleModel):
    """Sent from the client to request cancellation of resources/updated notifications from the server. This should follow a previous resources/subscribe request."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["resources/unsubscribe"]
    params: Params29


class Annotations(OracleModel):
    """Optional annotations for the client. The client can use annotations to inform how objects are used or displayed"""

    model_config = ConfigDict(
        extra="allow",
    )
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


class AudioContent(OracleModel):
    """Audio provided to or from an LLM."""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    data: Base64Str
    """
    The base64-encoded audio data.
    """
    mime_type: Annotated[str, Field(alias="mimeType")]
    """
    The MIME type of the audio. Different providers may support different audio types.
    """
    type: Literal["audio"]


class Params1(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    reason: str | None = None
    """
    An optional string describing the reason for the cancellation. This MAY be logged or presented to the user.
    """
    request_id: Annotated[RequestId, Field(alias="requestId")]
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    """


class CancelledNotification(OracleModel):
    """This notification can be sent by either side to indicate that it is cancelling a previously-issued request.

    The request SHOULD still be in-flight, but due to communication latency, it is always possible that this notification MAY arrive after the request has already finished.

    This notification indicates that the result will be unused, so any associated processing SHOULD cease.

    A client MUST NOT attempt to cancel its `initialize` request.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/cancelled"]
    params: Params1


class Params2(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    argument: Argument
    """
    The argument's information
    """
    context: Context | None = None
    """
    Additional, optional context for completions
    """
    ref: PromptReference | ResourceTemplateReference


class CompleteRequest(OracleModel):
    """A request from the client to the server, to ask for completion options."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["completion/complete"]
    params: Params2


class EmbeddedResource(OracleModel):
    """The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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


class ImageContent(OracleModel):
    """An image provided to or from an LLM."""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    annotations: Annotations | None = None
    """
    Optional annotations for the client.
    """
    data: Base64Str
    """
    The base64-encoded image data.
    """
    mime_type: Annotated[str, Field(alias="mimeType")]
    """
    The MIME type of the image. Different providers may support different image types.
    """
    type: Literal["image"]


class InitializeResult(OracleModel):
    """After receiving an initialize request from the client, the server sends this response."""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
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


class JSONRPCError(OracleModel):
    """A response to a request that indicates an error occurred."""

    model_config = ConfigDict(
        extra="allow",
    )
    error: Error
    id: RequestId
    jsonrpc: Literal["2.0"]


class Params9(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class JSONRPCRequest(OracleModel):
    """A request that expects a response."""

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    method: str
    params: Params9 | None = None


class JSONRPCResponse(OracleModel):
    """A successful (non-error) response to a request."""

    model_config = ConfigDict(
        extra="allow",
    )
    id: RequestId
    jsonrpc: Literal["2.0"]
    result: Result


class Params13(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class ListRootsRequest(OracleModel):
    """Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["roots/list"]
    params: Params13 | None = None


class ListRootsResult(OracleModel):
    """The client's response to a roots/list request from the server.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    roots: list[Root]


class Params18(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """


class PingRequest(OracleModel):
    """A ping, issued by either the server or the client, to check that the other party is still alive. The receiver must promptly respond, or else may be disconnected."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["ping"]
    params: Params18 | None = None


PrimitiveSchemaDefinition: TypeAlias = StringSchema | NumberSchema | BooleanSchema | EnumSchema


class Params19(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
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


class ProgressNotification(OracleModel):
    """An out-of-band notification used to inform the receiver of a progress update for a long-running request."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["notifications/progress"]
    params: Params19


class Prompt(OracleModel):
    """A prompt or prompt template that the server offers."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class ReadResourceResult(OracleModel):
    """The server's response to a resources/read request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None
    """
    See [General fields: `_meta`](/specification/2025-06-18/basic/index#meta) for notes on `_meta` usage.
    """
    contents: list[TextResourceContents | BlobResourceContents]


class Resource(OracleModel):
    """A known resource that the server is capable of reading."""

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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
    uri: AnyUrl
    """
    The URI of this resource.
    """


class ResourceLink(OracleModel):
    """A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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
    uri: AnyUrl
    """
    The URI of this resource.
    """


class ResourceTemplate(OracleModel):
    """A template description for resources available on the server."""

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available resources. It can be thought of like a "hint" to the model.
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


ServerNotification: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | ResourceListChangedNotification
    | ResourceUpdatedNotification
    | PromptListChangedNotification
    | ToolListChangedNotification
    | LoggingMessageNotification
)


class TextContent(OracleModel):
    """Text provided to or from an LLM."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class Tool(OracleModel):
    """Definition for a tool the client can call."""

    model_config = ConfigDict(
        extra="allow",
    )
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

    This can be used by clients to improve the LLM's understanding of available tools. It can be thought of like a "hint" to the model.
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


class CreateMessageResult(OracleModel):
    """The client's response to a sampling/create_message request from the server. The client should inform the user before returning the sampled message, to allow them to inspect the response (human in the loop) and decide whether to allow the server to see it."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class RequestedSchema(OracleModel):
    """A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None
    type: Literal["object"]


class Params4(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    message: str
    """
    The message to present to the user.
    """
    requested_schema: Annotated[RequestedSchema, Field(alias="requestedSchema")]
    """
    A restricted subset of JSON Schema.
    Only top-level properties are allowed, without nesting.
    """


class ElicitRequest(OracleModel):
    """A request from the server to elicit additional information from the user via the client."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["elicitation/create"]
    params: Params4


JSONRPCMessage: TypeAlias = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError


class ListPromptsResult(OracleModel):
    """The server's response to a prompts/list request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class ListResourceTemplatesResult(OracleModel):
    """The server's response to a resources/templates/list request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class ListResourcesResult(OracleModel):
    """The server's response to a resources/list request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class ListToolsResult(OracleModel):
    """The server's response to a tools/list request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
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


class PromptMessage(OracleModel):
    """Describes a message returned as part of a prompt.

    This is similar to `SamplingMessage`, but also supports the embedding of
    resources from the MCP server.
    """

    model_config = ConfigDict(
        extra="allow",
    )
    content: ContentBlock
    role: Role


class SamplingMessage(OracleModel):
    """Describes a message issued to or received from an LLM API."""

    model_config = ConfigDict(
        extra="allow",
    )
    content: TextContent | ImageContent | AudioContent
    role: Role


class CallToolResult(OracleModel):
    """The server's response to a tool call."""

    model_config = ConfigDict(
        extra="allow",
    )
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
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
    """
    An optional JSON object that represents the structured result of the tool call.
    """


ClientResult: TypeAlias = Result | CreateMessageResult | ListRootsResult | ElicitResult


class Params3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    include_context: Annotated[
        Literal["allServers", "none", "thisServer"] | None,
        Field(alias="includeContext"),
    ] = None
    """
    A request to include context from one or more MCP servers (including the caller), to be attached to the prompt. The client MAY ignore this request.
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


class CreateMessageRequest(OracleModel):
    """A request from the server to sample an LLM via the client. The client has full discretion over which model to select. The client should also inform the user before beginning sampling, to allow them to inspect the request (human in the loop) and decide whether to approve it."""

    model_config = ConfigDict(
        extra="allow",
    )
    method: Literal["sampling/createMessage"]
    params: Params3


class GetPromptResult(OracleModel):
    """The server's response to a prompts/get request from the client."""

    model_config = ConfigDict(
        extra="allow",
    )
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

SPEC_DEFS: tuple[str, ...] = (
    "Annotations",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "BooleanSchema",
    "CallToolRequest",
    "CallToolResult",
    "CancelledNotification",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteResult",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageResult",
    "Cursor",
    "ElicitRequest",
    "ElicitResult",
    "EmbeddedResource",
    "EmptyResult",
    "EnumSchema",
    "GetPromptRequest",
    "GetPromptResult",
    "ImageContent",
    "Implementation",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCError",
    "JSONRPCMessage",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourceTemplatesRequest",
    "ListResourceTemplatesResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListRootsRequest",
    "ListRootsResult",
    "ListToolsRequest",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "ModelHint",
    "ModelPreferences",
    "Notification",
    "NumberSchema",
    "PaginatedRequest",
    "PaginatedResult",
    "PingRequest",
    "PrimitiveSchemaDefinition",
    "ProgressNotification",
    "ProgressToken",
    "Prompt",
    "PromptArgument",
    "PromptListChangedNotification",
    "PromptMessage",
    "PromptReference",
    "ReadResourceRequest",
    "ReadResourceResult",
    "Request",
    "RequestId",
    "Resource",
    "ResourceContents",
    "ResourceLink",
    "ResourceListChangedNotification",
    "ResourceTemplate",
    "ResourceTemplateReference",
    "ResourceUpdatedNotification",
    "Result",
    "Role",
    "Root",
    "RootsListChangedNotification",
    "SamplingMessage",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "SetLevelRequest",
    "StringSchema",
    "SubscribeRequest",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "ToolListChangedNotification",
    "UnsubscribeRequest",
)
