"""The public import surface of `mcp.types` and the curated `mcp` top level.

The v2 base surface is a ratchet: every name importable from `mcp.types`
before the 2026-07-28 protocol work stays importable, byte for byte. The
additions are exactly the new protocol constructs; the curated `mcp` top
level gains nothing. A few v1 construction idioms (camelCase keyword
arguments, `_meta`/`meta` keywords, the module-level adapters) are spot
checked because downstream code relies on them.
"""

from typing import Any

from pydantic import TypeAdapter

import mcp
import mcp.types

V2_BASE_NAMES = frozenset(
    {
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
    }
)
"""Every name `mcp.types.__all__` carried before the 2026-07-28 additions."""

ADDED_NAMES = frozenset(
    {
        "CLIENT_CAPABILITIES_META_KEY",
        "CLIENT_INFO_META_KEY",
        "CacheableResult",
        "CancelTaskRequest",
        "CancelTaskRequestParams",
        "CancelTaskResult",
        "CreateTaskResult",
        "DiscoverRequest",
        "DiscoverResult",
        "GetTaskPayloadRequest",
        "GetTaskPayloadRequestParams",
        "GetTaskPayloadResult",
        "GetTaskRequest",
        "GetTaskRequestParams",
        "GetTaskResult",
        "InputRequest",
        "InputRequests",
        "InputRequiredResult",
        "InputResponse",
        "InputResponseRequestParams",
        "InputResponses",
        "JSONRPC_VERSION",
        "LOG_LEVEL_META_KEY",
        "ListTasksRequest",
        "ListTasksResult",
        "MISSING_REQUIRED_CLIENT_CAPABILITY",
        "MissingRequiredClientCapabilityErrorData",
        "PROTOCOL_VERSION_META_KEY",
        "RelatedTaskMetadata",
        "ResultType",
        "SubscriptionFilter",
        "SubscriptionsAcknowledgedNotification",
        "SubscriptionsAcknowledgedNotificationParams",
        "SubscriptionsListenRequest",
        "SubscriptionsListenRequestParams",
        "Task",
        "TaskMetadata",
        "TaskStatus",
        "TaskStatusNotification",
        "TaskStatusNotificationParams",
        "ToolExecution",
        "UNSUPPORTED_PROTOCOL_VERSION",
        "UnsupportedProtocolVersionErrorData",
    }
)
"""The 2026-07-28-cycle additions, including the restored 2025-11-25 task types."""

MCP_TOP_LEVEL_NAMES = frozenset(
    {
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
        "ResourceUpdatedNotification",
        "ResourcesCapability",
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
        "ToolUseContent",
        "ToolsCapability",
        "UnsubscribeRequest",
        "UrlElicitationRequiredError",
        "stdio_client",
        "stdio_server",
    }
)


def test_types_surface_is_the_v2_base_set_plus_the_additions() -> None:
    assert set(mcp.types.__all__) == V2_BASE_NAMES | ADDED_NAMES
    assert len(mcp.types.__all__) == len(set(mcp.types.__all__))


def test_no_v2_base_name_was_removed() -> None:
    """The ratchet direction stated on its own: removals are breaking."""
    assert V2_BASE_NAMES <= set(mcp.types.__all__)


def test_every_exported_name_is_importable() -> None:
    for name in mcp.types.__all__:
        assert getattr(mcp.types, name) is not None


def test_curated_top_level_surface_is_unchanged() -> None:
    assert set(mcp.__all__) == MCP_TOP_LEVEL_NAMES
    assert len(mcp.__all__) == len(MCP_TOP_LEVEL_NAMES)


def test_camel_case_keyword_arguments_still_construct() -> None:
    camel_result: dict[str, Any] = {"tools": [], "nextCursor": "cursor"}
    assert mcp.types.ListToolsResult(**camel_result).next_cursor == "cursor"
    camel_tool: dict[str, Any] = {"name": "t", "inputSchema": {"type": "object"}}
    assert mcp.types.Tool(**camel_tool).input_schema == {"type": "object"}


def test_meta_keyword_accepted_under_both_names() -> None:
    by_alias_kwargs: dict[str, Any] = {"content": [], "_meta": {"k": 1}}
    by_name_kwargs: dict[str, Any] = {"content": [], "meta": {"k": 1}}
    by_alias = mcp.types.CallToolResult(**by_alias_kwargs)
    by_name = mcp.types.CallToolResult(**by_name_kwargs)
    assert by_alias.meta == by_name.meta == {"k": 1}


def test_module_level_adapters_exist() -> None:
    for name in (
        "client_request_adapter",
        "client_notification_adapter",
        "client_result_adapter",
        "server_request_adapter",
        "server_notification_adapter",
        "server_result_adapter",
        "jsonrpc_message_adapter",
    ):
        assert isinstance(getattr(mcp.types, name), TypeAdapter)
