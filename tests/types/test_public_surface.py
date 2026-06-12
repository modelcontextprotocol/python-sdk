"""Pin the public type surface against the fork-point baseline.

``mcp.types.__all__`` is a one-way compatibility ratchet: every name the
module exported at the fork point is still exported (zero removals), and this
branch adds exactly the names in ``_ADDED_EXPORTS`` — nothing else. The
curated top-level surface (``mcp.__all__``) gains nothing. Negotiation
defaults are pinned unchanged: modeling the 2026-07-28 protocol revision must
not change which protocol versions the SDK advertises or negotiates.
"""

from __future__ import annotations

from typing import Any

import mcp
import mcp.types
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import CallToolRequestParams, Tool

_BASELINE_EXPORTS: tuple[str, ...] = (
    # `mcp.types.__all__` at the fork point (153 names, sorted). Removing any
    # of these is a breaking change; this tuple is never edited, only the
    # additions tuple below grows.
    "Annotations",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "CONNECTION_CLOSED",
    "CallToolRequest",
    "CallToolRequestParams",
    "CallToolResult",
    "CancelledNotification",
    "CancelledNotificationParams",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "CompleteRequest",
    "CompleteRequestParams",
    "CompleteResult",
    "Completion",
    "CompletionArgument",
    "CompletionContext",
    "CompletionsCapability",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageRequestParams",
    "CreateMessageResult",
    "CreateMessageResultWithTools",
    "DEFAULT_NEGOTIATED_VERSION",
    "ElicitCompleteNotification",
    "ElicitCompleteNotificationParams",
    "ElicitRequest",
    "ElicitRequestFormParams",
    "ElicitRequestParams",
    "ElicitRequestURLParams",
    "ElicitRequestedSchema",
    "ElicitResult",
    "ElicitationCapability",
    "ElicitationRequiredErrorData",
    "EmbeddedResource",
    "EmptyResult",
    "ErrorData",
    "FormElicitationCapability",
    "GetPromptRequest",
    "GetPromptRequestParams",
    "GetPromptResult",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "Icon",
    "IconTheme",
    "ImageContent",
    "Implementation",
    "IncludeContext",
    "InitializeRequest",
    "InitializeRequestParams",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCError",
    "JSONRPCMessage",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "LATEST_PROTOCOL_VERSION",
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
    "LoggingCapability",
    "LoggingLevel",
    "LoggingMessageNotification",
    "LoggingMessageNotificationParams",
    "METHOD_NOT_FOUND",
    "ModelHint",
    "ModelPreferences",
    "Notification",
    "NotificationParams",
    "PARSE_ERROR",
    "PaginatedRequest",
    "PaginatedRequestParams",
    "PaginatedResult",
    "PingRequest",
    "ProgressNotification",
    "ProgressNotificationParams",
    "ProgressToken",
    "Prompt",
    "PromptArgument",
    "PromptListChangedNotification",
    "PromptMessage",
    "PromptReference",
    "PromptsCapability",
    "REQUEST_CANCELLED",
    "REQUEST_TIMEOUT",
    "ReadResourceRequest",
    "ReadResourceRequestParams",
    "ReadResourceResult",
    "Request",
    "RequestId",
    "RequestParams",
    "RequestParamsMeta",
    "Resource",
    "ResourceContents",
    "ResourceLink",
    "ResourceListChangedNotification",
    "ResourceTemplate",
    "ResourceTemplateReference",
    "ResourceUpdatedNotification",
    "ResourceUpdatedNotificationParams",
    "ResourcesCapability",
    "Result",
    "Role",
    "Root",
    "RootsCapability",
    "RootsListChangedNotification",
    "SamplingCapability",
    "SamplingContent",
    "SamplingContextCapability",
    "SamplingMessage",
    "SamplingMessageContentBlock",
    "SamplingToolsCapability",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "SetLevelRequest",
    "SetLevelRequestParams",
    "StopReason",
    "SubscribeRequest",
    "SubscribeRequestParams",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "ToolChoice",
    "ToolListChangedNotification",
    "ToolResultContent",
    "ToolUseContent",
    "ToolsCapability",
    "URL_ELICITATION_REQUIRED",
    "UnsubscribeRequest",
    "UnsubscribeRequestParams",
    "UrlElicitationCapability",
    "client_notification_adapter",
    "client_request_adapter",
    "client_result_adapter",
    "jsonrpc_message_adapter",
    "server_notification_adapter",
    "server_request_adapter",
    "server_result_adapter",
)

_ADDED_EXPORTS: tuple[str, ...] = (
    # Everything this branch adds to `mcp.types.__all__` (43 names). Grouped
    # by the protocol feature that introduces each name.
    #
    # JSON-RPC protocol identifier, re-exported from mcp.types.jsonrpc.
    "JSONRPC_VERSION",
    # Result completion state, added in 2026-07-28 (absent means complete).
    "ResultType",
    # Client-side caching directives on results, added in 2026-07-28.
    "CacheableResult",
    # The server/discover lifecycle request, added in 2026-07-28.
    "DiscoverRequest",
    "DiscoverResult",
    # Filtered resource subscriptions, added in 2026-07-28.
    "SubscriptionFilter",
    "SubscriptionsAcknowledgedNotification",
    "SubscriptionsAcknowledgedNotificationParams",
    "SubscriptionsListenRequest",
    "SubscriptionsListenRequestParams",
    # Server-initiated input requests during sampling, added in 2026-07-28.
    "InputRequest",
    "InputRequests",
    "InputRequiredResult",
    "InputResponse",
    "InputResponseRequestParams",
    "InputResponses",
    # Error payloads and codes, added in 2026-07-28.
    "MISSING_REQUIRED_CLIENT_CAPABILITY",
    "MissingRequiredClientCapabilityErrorData",
    "UNSUPPORTED_PROTOCOL_VERSION",
    "UnsupportedProtocolVersionErrorData",
    # Reserved `_meta` key names, added in 2026-07-28.
    "CLIENT_CAPABILITIES_META_KEY",
    "CLIENT_INFO_META_KEY",
    "LOG_LEVEL_META_KEY",
    "PROTOCOL_VERSION_META_KEY",
    # Task types from 2025-11-25, modeled again so that sessions negotiating
    # that version can exchange them (the methods were removed in 2026-07-28).
    "CancelTaskRequest",
    "CancelTaskRequestParams",
    "CancelTaskResult",
    "CreateTaskResult",
    "GetTaskPayloadRequest",
    "GetTaskPayloadRequestParams",
    "GetTaskPayloadResult",
    "GetTaskRequest",
    "GetTaskRequestParams",
    "GetTaskResult",
    "ListTasksRequest",
    "ListTasksResult",
    "RelatedTaskMetadata",
    "Task",
    "TaskMetadata",
    "TaskStatus",
    "TaskStatusNotification",
    "TaskStatusNotificationParams",
    "ToolExecution",
)

_TOP_LEVEL_EXPORTS: tuple[str, ...] = (
    # `mcp.__all__` at the fork point (66 names, original order). This branch
    # adds nothing to the curated top-level surface.
    "CallToolRequest",
    "Client",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "ClientSession",
    "ClientSessionGroup",
    "CompleteRequest",
    "CreateMessageRequest",
    "CreateMessageResult",
    "CreateMessageResultWithTools",
    "ErrorData",
    "GetPromptRequest",
    "GetPromptResult",
    "Implementation",
    "IncludeContext",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCError",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "MCPError",
    "Notification",
    "PingRequest",
    "ProgressNotification",
    "PromptsCapability",
    "ReadResourceRequest",
    "ReadResourceResult",
    "Resource",
    "ResourcesCapability",
    "ResourceUpdatedNotification",
    "RootsCapability",
    "SamplingCapability",
    "SamplingContent",
    "SamplingContextCapability",
    "SamplingMessage",
    "SamplingMessageContentBlock",
    "SamplingRole",
    "SamplingToolsCapability",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "ServerSession",
    "SetLevelRequest",
    "StdioServerParameters",
    "StopReason",
    "SubscribeRequest",
    "Tool",
    "ToolChoice",
    "ToolResultContent",
    "ToolsCapability",
    "ToolUseContent",
    "UnsubscribeRequest",
    "UrlElicitationRequiredError",
    "stdio_client",
    "stdio_server",
)


def test_pinned_lists_are_internally_consistent() -> None:
    """Self-check on the pinned data: counts, no duplicates, no overlap."""
    assert len(_BASELINE_EXPORTS) == 153
    assert len(set(_BASELINE_EXPORTS)) == 153
    assert len(_ADDED_EXPORTS) == 43
    assert len(set(_ADDED_EXPORTS)) == 43
    assert set(_BASELINE_EXPORTS) & set(_ADDED_EXPORTS) == set()
    assert len(_TOP_LEVEL_EXPORTS) == 66


def test_types_exports_are_baseline_plus_exactly_the_additions() -> None:
    """`mcp.types.__all__` keeps every fork-point name and adds only the pinned names."""
    exported = set(mcp.types.__all__)
    removed = set(_BASELINE_EXPORTS) - exported
    assert removed == set(), f"fork-point exports must never be removed: {sorted(removed)}"
    assert exported - set(_BASELINE_EXPORTS) == set(_ADDED_EXPORTS)


def test_types_export_list_has_no_duplicates() -> None:
    """`mcp.types.__all__` lists each name exactly once."""
    assert len(mcp.types.__all__) == len(set(mcp.types.__all__))


def test_every_types_export_resolves() -> None:
    """Every name in `mcp.types.__all__` is an attribute of the module."""
    missing = [name for name in mcp.types.__all__ if not hasattr(mcp.types, name)]
    assert missing == []


def test_top_level_exports_unchanged() -> None:
    """`mcp.__all__` is exactly the fork-point list, in the same order."""
    assert list(mcp.__all__) == list(_TOP_LEVEL_EXPORTS)


def test_negotiation_defaults_unchanged() -> None:
    """The SDK advertises and negotiates the same versions as at the fork point.

    2026-07-28 types are modeled, but the version is not offered during
    negotiation; enabling it is a separate, deliberate change.
    """
    assert mcp.types.LATEST_PROTOCOL_VERSION == "2025-11-25"
    assert mcp.types.DEFAULT_NEGOTIATED_VERSION == "2025-03-26"
    assert SUPPORTED_PROTOCOL_VERSIONS == ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]


def test_wire_name_constructor_kwargs_still_work() -> None:
    """Models keep accepting wire-name (camelCase) constructor kwargs.

    The static signature lists only the snake_case field names, so the
    wire-name spelling is passed as an unpacked dict; at runtime both
    spellings construct the same model.
    """
    wire_name_kwargs: dict[str, Any] = {"name": "t", "inputSchema": {"type": "object"}}
    assert Tool(**wire_name_kwargs) == Tool(name="t", input_schema={"type": "object"})


def test_meta_constructor_kwargs_still_work() -> None:
    """Request params accept both the `_meta` wire alias and the `meta` field name.

    The static signature lists only the `_meta` spelling, so the field-name
    spelling is passed as an unpacked dict; at runtime both spellings
    construct the same model.
    """
    field_name_kwargs: dict[str, Any] = {"name": "t", "meta": {"k": "v"}}
    assert CallToolRequestParams(**field_name_kwargs) == CallToolRequestParams(name="t", _meta={"k": "v"})
