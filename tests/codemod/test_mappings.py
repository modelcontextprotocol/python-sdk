"""Pin the codemod's mapping tables against the installed v2 package.

Each table is pinned as an exact literal and checked against the installed
packages; a failure here means the table is wrong, not the transformer.
"""

import inspect
from importlib import import_module
from importlib.metadata import metadata
from importlib.util import find_spec

import mcp_types
import pytest
from mcp_codemod import transform
from mcp_codemod._adapters import LOWLEVEL_HANDLER_SPECS
from mcp_codemod._mappings import (
    CAMEL_FIELDS,
    LOWLEVEL_CTOR_POSITIONAL_PARAMS,
    LOWLEVEL_REMOVED_ATTRS,
    MODULE_RENAMES,
    REHOMED_IMPORTS,
    REMOVED_APIS,
    REMOVED_ATTRS,
    REMOVED_CTOR_PARAMS,
    REMOVED_EXTRAS,
    REMOVED_MODULES,
    SYMBOL_RENAMES,
    TRANSPORT_CLIENT_REMOVED_PARAMS,
    TRANSPORT_CTOR_PARAMS,
)
from pydantic import BaseModel

import mcp.client.session
import mcp.server.mcpserver
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.mcpserver import Context, MCPServer


def _v2_resolves(qualified: str) -> bool:
    """Whether a dotted name resolves on the installed v2 package."""
    module_path, _, attribute = qualified.rpartition(".")
    try:
        return hasattr(import_module(module_path), attribute)
    except ImportError:
        return False


def test_the_module_rename_table_is_exact_and_every_target_imports() -> None:
    assert MODULE_RENAMES == {
        "mcp.server.fastmcp": "mcp.server.mcpserver",
        "mcp.server.fastmcp.server": "mcp.server.mcpserver.server",
        "mcp.shared.version": "mcp_types.version",
        "mcp.types": "mcp_types",
    }
    for target in MODULE_RENAMES.values():
        import_module(target)


def test_the_symbol_rename_table_is_exact() -> None:
    """The symbol table covers every v1 import path of each renamed name, and nothing else."""
    assert SYMBOL_RENAMES == {
        "mcp.server.FastMCP": "MCPServer",
        "mcp.server.fastmcp.FastMCP": "MCPServer",
        "mcp.server.fastmcp.server.FastMCP": "MCPServer",
        "mcp.server.fastmcp.exceptions.FastMCPError": "MCPServerError",
        "mcp.McpError": "MCPError",
        "mcp.shared.exceptions.McpError": "MCPError",
        "mcp.client.streamable_http.streamablehttp_client": "streamable_http_client",
        "mcp.types.Content": "ContentBlock",
        "mcp.types.ResourceReference": "ResourceTemplateReference",
    }


@pytest.mark.parametrize(("qualified", "new_name"), sorted(SYMBOL_RENAMES.items()))
def test_rewriting_an_import_of_each_renamed_symbol_resolves_on_v2(qualified: str, new_name: str) -> None:
    module_path, _, old_name = qualified.rpartition(".")
    rewritten = transform(f"from {module_path} import {old_name}\n").code
    namespace: dict[str, object] = {}
    exec(rewritten, namespace)
    assert new_name in namespace


def test_every_removed_api_is_absent_from_the_installed_v2_package() -> None:
    assert set(REMOVED_APIS) == {
        "mcp.client.websocket.websocket_client",
        "mcp.os.win32.utilities.terminate_windows_process",
        "mcp.server.websocket.websocket_server",
        "mcp.shared.context.RequestContext",
        "mcp.shared.memory.create_connected_server_and_client_session",
        "mcp.server.lowlevel.server.request_ctx",
        "mcp.shared.progress.Progress",
        "mcp.shared.progress.ProgressContext",
        "mcp.shared.progress.progress",
        "mcp.shared.session.BaseSession",
        "mcp.types.AnyFunction",
        "mcp.types.ClientNotificationType",
        "mcp.types.ClientRequestType",
        "mcp.types.ClientResultType",
        "mcp.types.Cursor",
        "mcp.types.MethodT",
        "mcp.types.RequestParams.Meta",
        "mcp.types.NotificationParamsT",
        "mcp.types.RequestParamsT",
        "mcp.types.ServerNotificationType",
        "mcp.types.ServerRequestType",
        "mcp.types.ServerResultType",
        "mcp.types.TASK_FORBIDDEN",
        "mcp.types.TASK_OPTIONAL",
        "mcp.types.TASK_REQUIRED",
        "mcp.types.TASK_STATUS_CANCELLED",
        "mcp.types.TASK_STATUS_COMPLETED",
        "mcp.types.TASK_STATUS_FAILED",
        "mcp.types.TASK_STATUS_INPUT_REQUIRED",
        "mcp.types.TASK_STATUS_WORKING",
        "mcp.types.TaskExecutionMode",
    }
    for qualified in REMOVED_APIS:
        assert not _v2_resolves(qualified), qualified


def test_every_camelcase_rename_target_is_a_field_on_an_installed_v2_model() -> None:
    assert len(CAMEL_FIELDS) == 40
    v2_fields = {
        name
        for obj in vars(mcp_types).values()
        if inspect.isclass(obj) and issubclass(obj, BaseModel)
        for name in obj.model_fields
    }
    for camel, field in CAMEL_FIELDS.items():
        assert field.snake in v2_fields, camel


def test_progress_token_is_in_the_risky_tier() -> None:
    """`ProgressNotificationParams` renamed it to `progress_token`, but `RequestParams.Meta`
    kept the camelCase wire spelling -- so an unconditional rename is wrong and needs human eyes."""
    assert CAMEL_FIELDS["progressToken"].tier == "risky"


def test_the_constructor_keyword_tables_match_the_v2_signatures() -> None:
    """Flagging a keyword v2 kept would be a lie (`debug`, `log_level`, and `dependencies`
    each survived one alpha or another). Landing spots are not asserted: `MCPServer.run`
    forwards `**kwargs` to the app builders, so its signature cannot show them."""
    constructor = set(inspect.signature(MCPServer.__init__).parameters)
    assert not (TRANSPORT_CTOR_PARAMS | set(REMOVED_CTOR_PARAMS)) & constructor
    # If v2 grew a v1 decorator name back as a live method, deleting the decorator would break code.
    assert not set(LOWLEVEL_HANDLER_SPECS) & set(dir(Server))


# Every public top-level name of v1's `mcp/types.py`, frozen from `origin/v1.x`.
_V1_TYPES_PUBLIC_NAMES = (
    "Annotations",
    "AnyFunction",
    "AudioContent",
    "BaseMetadata",
    "BlobResourceContents",
    "CONNECTION_CLOSED",
    "CallToolRequest",
    "CallToolRequestParams",
    "CallToolResult",
    "CancelTaskRequest",
    "CancelTaskRequestParams",
    "CancelTaskResult",
    "CancelledNotification",
    "CancelledNotificationParams",
    "ClientCapabilities",
    "ClientNotification",
    "ClientNotificationType",
    "ClientRequest",
    "ClientRequestType",
    "ClientResult",
    "ClientResultType",
    "ClientTasksCapability",
    "ClientTasksRequestsCapability",
    "CompleteRequest",
    "CompleteRequestParams",
    "CompleteResult",
    "Completion",
    "CompletionArgument",
    "CompletionContext",
    "CompletionsCapability",
    "Content",
    "ContentBlock",
    "CreateMessageRequest",
    "CreateMessageRequestParams",
    "CreateMessageResult",
    "CreateMessageResultWithTools",
    "CreateTaskResult",
    "Cursor",
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
    "GetTaskPayloadRequest",
    "GetTaskPayloadRequestParams",
    "GetTaskPayloadResult",
    "GetTaskRequest",
    "GetTaskRequestParams",
    "GetTaskResult",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "Icon",
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
    "ListTasksRequest",
    "ListTasksResult",
    "ListToolsRequest",
    "ListToolsResult",
    "LoggingCapability",
    "LoggingLevel",
    "LoggingMessageNotification",
    "LoggingMessageNotificationParams",
    "METHOD_NOT_FOUND",
    "MethodT",
    "ModelHint",
    "ModelPreferences",
    "Notification",
    "NotificationParams",
    "NotificationParamsT",
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
    "ReadResourceRequest",
    "ReadResourceRequestParams",
    "ReadResourceResult",
    "RelatedTaskMetadata",
    "Request",
    "RequestId",
    "RequestParams",
    "RequestParamsT",
    "Resource",
    "ResourceContents",
    "ResourceLink",
    "ResourceListChangedNotification",
    "ResourceReference",
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
    "ServerNotificationType",
    "ServerRequest",
    "ServerRequestType",
    "ServerResult",
    "ServerResultType",
    "ServerTasksCapability",
    "ServerTasksRequestsCapability",
    "SetLevelRequest",
    "SetLevelRequestParams",
    "StopReason",
    "SubscribeRequest",
    "SubscribeRequestParams",
    "TASK_FORBIDDEN",
    "TASK_OPTIONAL",
    "TASK_REQUIRED",
    "TASK_STATUS_CANCELLED",
    "TASK_STATUS_COMPLETED",
    "TASK_STATUS_FAILED",
    "TASK_STATUS_INPUT_REQUIRED",
    "TASK_STATUS_WORKING",
    "Task",
    "TaskExecutionMode",
    "TaskMetadata",
    "TaskStatus",
    "TaskStatusNotification",
    "TaskStatusNotificationParams",
    "TasksCallCapability",
    "TasksCancelCapability",
    "TasksCreateElicitationCapability",
    "TasksCreateMessageCapability",
    "TasksElicitationCapability",
    "TasksListCapability",
    "TasksSamplingCapability",
    "TasksToolsCapability",
    "TextContent",
    "TextResourceContents",
    "Tool",
    "ToolAnnotations",
    "ToolChoice",
    "ToolExecution",
    "ToolListChangedNotification",
    "ToolResultContent",
    "ToolUseContent",
    "ToolsCapability",
    "URL_ELICITATION_REQUIRED",
    "UnsubscribeRequest",
    "UnsubscribeRequestParams",
    "UrlElicitationCapability",
)


def test_every_public_name_of_a_renamed_v1_module_is_importable_or_accounted_for() -> None:
    """Every public name of a renamed v1 module must import from the rename target,
    or be in `SYMBOL_RENAMES` or `REMOVED_APIS`; anything else lets the codemod
    emit an import that cannot resolve, with no diagnostic."""
    renamed_v1_modules = {
        "mcp.types": _V1_TYPES_PUBLIC_NAMES,
        # v1's `mcp/server/fastmcp/__init__.py` declared this `__all__` explicitly.
        "mcp.server.fastmcp": ("FastMCP", "Context", "Image", "Audio", "Icon"),
        # Only the names users import; the module's other definitions are internals.
        "mcp.server.fastmcp.server": ("FastMCP", "Context", "Settings"),
        "mcp.shared.version": ("LATEST_PROTOCOL_VERSION", "SUPPORTED_PROTOCOL_VERSIONS"),
    }
    assert set(renamed_v1_modules) == set(MODULE_RENAMES)
    unaccounted = [
        f"{old}.{name}"
        for old, names in renamed_v1_modules.items()
        for name in names
        if not hasattr(import_module(MODULE_RENAMES[old]), name)
        and f"{old}.{name}" not in SYMBOL_RENAMES
        and f"{old}.{name}" not in REMOVED_APIS
    ]
    assert unaccounted == []


def test_no_removed_attribute_name_is_spelled_by_a_living_v2_api() -> None:
    """`REMOVED_ATTRS` matches by name alone, so a name qualifies only if nothing
    public on v2 still spells it -- `request_context` fails exactly this bar."""
    assert set(REMOVED_ATTRS) == {"get_context", "get_server_capabilities", "_mcp_server"}
    # The private-name row: v2 really renamed the wrapped server, both spellings private.
    assert not hasattr(MCPServer, "_mcp_server")
    assert "_lowlevel_server" in vars(MCPServer("probe"))
    living = {
        name
        for module in (mcp, mcp.client.session, mcp.server.mcpserver, mcp_types)
        for obj in vars(module).values()
        if inspect.isclass(obj)
        for name in dir(obj)
        if not name.startswith("_")
    }
    assert "request_context" in living
    assert not set(REMOVED_ATTRS) & living


def test_the_removed_client_keyword_set_is_exactly_v1_minus_v2() -> None:
    """Flagging a keyword v2 kept would be a lie; missing one v2 dropped is a silent
    `TypeError`. v1's signature is frozen history; v2's is introspected."""
    v1_parameters = frozenset(
        {"url", "headers", "timeout", "sse_read_timeout", "terminate_on_close", "httpx_client_factory", "auth"}
    )
    v2_parameters = frozenset(inspect.signature(streamable_http_client).parameters)
    assert v1_parameters - v2_parameters == TRANSPORT_CLIENT_REMOVED_PARAMS


# Every public module v1 shipped (no underscore path segment), frozen from `origin/v1.x`.
_V1_PUBLIC_MODULES = (
    "mcp",
    "mcp.cli",
    "mcp.cli.claude",
    "mcp.cli.cli",
    "mcp.client",
    "mcp.client.auth",
    "mcp.client.auth.exceptions",
    "mcp.client.auth.extensions",
    "mcp.client.auth.extensions.client_credentials",
    "mcp.client.auth.oauth2",
    "mcp.client.auth.utils",
    "mcp.client.experimental",
    "mcp.client.experimental.task_handlers",
    "mcp.client.experimental.tasks",
    "mcp.client.session",
    "mcp.client.session_group",
    "mcp.client.sse",
    "mcp.client.stdio",
    "mcp.client.streamable_http",
    "mcp.client.websocket",
    "mcp.os",
    "mcp.os.posix",
    "mcp.os.posix.utilities",
    "mcp.os.win32",
    "mcp.os.win32.utilities",
    "mcp.server",
    "mcp.server.auth",
    "mcp.server.auth.errors",
    "mcp.server.auth.handlers",
    "mcp.server.auth.handlers.authorize",
    "mcp.server.auth.handlers.metadata",
    "mcp.server.auth.handlers.register",
    "mcp.server.auth.handlers.revoke",
    "mcp.server.auth.handlers.token",
    "mcp.server.auth.json_response",
    "mcp.server.auth.middleware",
    "mcp.server.auth.middleware.auth_context",
    "mcp.server.auth.middleware.bearer_auth",
    "mcp.server.auth.middleware.client_auth",
    "mcp.server.auth.provider",
    "mcp.server.auth.routes",
    "mcp.server.auth.settings",
    "mcp.server.elicitation",
    "mcp.server.experimental",
    "mcp.server.experimental.request_context",
    "mcp.server.experimental.session_features",
    "mcp.server.experimental.task_context",
    "mcp.server.experimental.task_result_handler",
    "mcp.server.experimental.task_scope",
    "mcp.server.experimental.task_support",
    "mcp.server.fastmcp",
    "mcp.server.fastmcp.exceptions",
    "mcp.server.fastmcp.prompts",
    "mcp.server.fastmcp.prompts.base",
    "mcp.server.fastmcp.prompts.manager",
    "mcp.server.fastmcp.resources",
    "mcp.server.fastmcp.resources.base",
    "mcp.server.fastmcp.resources.resource_manager",
    "mcp.server.fastmcp.resources.templates",
    "mcp.server.fastmcp.resources.types",
    "mcp.server.fastmcp.server",
    "mcp.server.fastmcp.tools",
    "mcp.server.fastmcp.tools.base",
    "mcp.server.fastmcp.tools.tool_manager",
    "mcp.server.fastmcp.utilities",
    "mcp.server.fastmcp.utilities.context_injection",
    "mcp.server.fastmcp.utilities.func_metadata",
    "mcp.server.fastmcp.utilities.logging",
    "mcp.server.fastmcp.utilities.types",
    "mcp.server.lowlevel",
    "mcp.server.lowlevel.experimental",
    "mcp.server.lowlevel.func_inspection",
    "mcp.server.lowlevel.helper_types",
    "mcp.server.lowlevel.server",
    "mcp.server.models",
    "mcp.server.session",
    "mcp.server.sse",
    "mcp.server.stdio",
    "mcp.server.streamable_http",
    "mcp.server.streamable_http_manager",
    "mcp.server.transport_security",
    "mcp.server.validation",
    "mcp.server.websocket",
    "mcp.shared",
    "mcp.shared.auth",
    "mcp.shared.auth_utils",
    "mcp.shared.context",
    "mcp.shared.exceptions",
    "mcp.shared.experimental",
    "mcp.shared.experimental.tasks",
    "mcp.shared.experimental.tasks.capabilities",
    "mcp.shared.experimental.tasks.context",
    "mcp.shared.experimental.tasks.helpers",
    "mcp.shared.experimental.tasks.in_memory_task_store",
    "mcp.shared.experimental.tasks.message_queue",
    "mcp.shared.experimental.tasks.polling",
    "mcp.shared.experimental.tasks.resolver",
    "mcp.shared.experimental.tasks.store",
    "mcp.shared.memory",
    "mcp.shared.message",
    "mcp.shared.metadata_utils",
    "mcp.shared.progress",
    "mcp.shared.response_router",
    "mcp.shared.session",
    "mcp.shared.tool_name_validation",
    "mcp.shared.version",
    "mcp.types",
)


def test_every_v1_module_resolves_on_v2_or_is_renamed_or_removed() -> None:
    """An unaccounted module would mean an import the codemod neither fixes nor flags;
    removed roots must really be gone from v2 and each must cover a v1 module."""

    def covered_by(table: dict[str, str], module: str) -> bool:
        return any(module == root or module.startswith(f"{root}.") for root in table)

    unaccounted = [
        module
        for module in _V1_PUBLIC_MODULES
        if not covered_by(MODULE_RENAMES, module)
        and not covered_by(REMOVED_MODULES, module)
        and find_spec(module) is None
    ]
    assert unaccounted == []
    for root in REMOVED_MODULES:
        assert find_spec(root) is None, root
        assert any(module == root or module.startswith(f"{root}.") for module in _V1_PUBLIC_MODULES), root


def test_the_removed_extras_are_exactly_v1_minus_the_installed_v2() -> None:
    """Flagging an extra v2 kept would be a lie; missing one v2 dropped leaves a
    constraint that cannot resolve. v1's set is frozen history."""
    v1_extras = {"cli", "rich", "ws"}
    v2_extras = set(metadata("mcp").get_all("Provides-Extra") or [])
    assert v1_extras - v2_extras == set(REMOVED_EXTRAS)


def test_every_rehomed_import_points_at_a_declared_public_export() -> None:
    """The target must declare the name in `__all__`, and the source must still hold
    it, so the rehome is never load-bearing for runtime behaviour."""
    for (source_module, name), target in REHOMED_IMPORTS.items():
        assert name in getattr(import_module(target), "__all__", []), (source_module, name)
        assert hasattr(import_module(source_module), name), (source_module, name)


def test_every_lowlevel_removed_attribute_is_really_gone_from_the_v2_server() -> None:
    """Each entry must be absent from the v2 `Server` yet spelled by some other
    living API -- otherwise plain name-matched `REMOVED_ATTRS` is its cheaper home."""
    assert set(LOWLEVEL_REMOVED_ATTRS) == {"request_context", "request_handlers", "notification_handlers"}
    for name in LOWLEVEL_REMOVED_ATTRS:
        assert not hasattr(Server, name), name
    # `request_context` survives on `Context` (the reason the table is receiver-gated);
    # the handler dicts' replacement API must exist for their guidance to hold.
    assert hasattr(Context, "request_context")
    assert hasattr(Server, "add_request_handler") and hasattr(Server, "get_request_handler")
    assert hasattr(Server, "add_notification_handler")


def test_the_lowlevel_positional_params_are_keyword_only_on_the_installed_server() -> None:
    """The rewrite emits these as keywords, so each must exist under that name on v2."""
    parameters = inspect.signature(Server.__init__).parameters
    for name in LOWLEVEL_CTOR_POSITIONAL_PARAMS:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
