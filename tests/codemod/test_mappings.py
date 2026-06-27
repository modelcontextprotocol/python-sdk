"""Pin the codemod's mapping tables against the installed v2 package.

The tables in `mcp_codemod._mappings` drive every rewrite the tool makes, so each
one is held to two bars here: an exact literal so a silently-deleted row can never
shrink the suite, and a check against the installed `mcp` / `mcp_types` packages
so a rename target or a removal claim cannot drift as v2 evolves. A failure here
means the table is wrong, not the transformer.
"""

import inspect
from importlib import import_module

import mcp_types
import pytest
from mcp_codemod import transform
from mcp_codemod._mappings import (
    CAMEL_FIELDS,
    LOWLEVEL_DECORATOR_METHODS,
    MODULE_RENAMES,
    REMOVED_APIS,
    REMOVED_ATTRS,
    REMOVED_CTOR_PARAMS,
    SYMBOL_RENAMES,
    TRANSPORT_CLIENT_REMOVED_PARAMS,
    TRANSPORT_CTOR_PARAMS,
)
from pydantic import BaseModel

import mcp.client.session
import mcp.server.mcpserver
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.mcpserver import MCPServer


def _v2_resolves(qualified: str) -> bool:
    """Whether a dotted name resolves on the installed v2 package."""
    module_path, _, attribute = qualified.rpartition(".")
    try:
        return hasattr(import_module(module_path), attribute)
    except ImportError:
        return False


def test_the_module_rename_table_is_exact_and_every_target_imports() -> None:
    """The module table is exactly the known set of moves, and every target exists on v2."""
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
    """Transforming a v1 import of a renamed symbol yields an import the installed v2 satisfies."""
    module_path, _, old_name = qualified.rpartition(".")
    rewritten = transform(f"from {module_path} import {old_name}\n").code
    namespace: dict[str, object] = {}
    exec(rewritten, namespace)
    assert new_name in namespace


def test_every_removed_api_is_absent_from_the_installed_v2_package() -> None:
    """Each flagged removal really is gone from v2; if one comes back, its flag becomes a lie."""
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
    """Each snake_case target really is a v2 field, so the rename never invents a name."""
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
    """`progressToken` had two v1 homes with two v2 fates: `ProgressNotificationParams`
    renamed it to `progress_token`, but `RequestParams.Meta` became a TypedDict keyed
    by the camelCase wire spelling, so a rename there is wrong and needs human eyes.
    """
    assert CAMEL_FIELDS["progressToken"].tier == "risky"


def test_the_constructor_keyword_tables_match_the_v2_signatures() -> None:
    """No flagged constructor keyword survives on the v2 `MCPServer.__init__`, and every
    lowlevel decorator maps to a real `on_*` keyword on the v2 `Server`. A keyword v2
    kept that the tables flag (`debug`, `log_level`, and `dependencies` all survived
    one alpha or another) would tell the user a lie they cannot reconcile.

    Where each moved keyword landed is not asserted here: `MCPServer.run` forwards
    `**kwargs` to the app builders, so its signature cannot show them.
    """
    constructor = set(inspect.signature(MCPServer.__init__).parameters)
    assert not (TRANSPORT_CTOR_PARAMS | set(REMOVED_CTOR_PARAMS)) & constructor
    assert set(LOWLEVEL_DECORATOR_METHODS.values()) <= set(inspect.signature(Server.__init__).parameters)


# Every name defined publicly at the top level of v1's `mcp/types.py`, extracted
# from `origin/v1.x` and frozen here because v1 is closed history. See the test
# below for why the codemod must account for every single one.
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
    """A module rename promises that what a file imported from the old module can be
    imported from the new one. For every public name v1 defined there, that has to
    be literally true of the installed v2 package -- or the name must be in
    `SYMBOL_RENAMES` (it gets rewritten) or `REMOVED_APIS` (it gets marked).
    Anything else would let the codemod produce an import that cannot resolve, with
    no diagnostic. The name lists are v1's, so they are frozen history; a new
    `MODULE_RENAMES` row must bring its own list here.
    """
    renamed_v1_modules = {
        "mcp.types": _V1_TYPES_PUBLIC_NAMES,
        # v1's `mcp/server/fastmcp/__init__.py` declared this `__all__` explicitly.
        "mcp.server.fastmcp": ("FastMCP", "Context", "Image", "Audio", "Icon"),
        # The names users import from the `server` module itself; its other
        # module-level definitions are internals nobody imports.
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
    """The removed-attribute table matches by NAME alone, so a name only qualifies if
    nothing public on v2 still spells it; otherwise the marker would flag working
    code. `request_context` fails exactly this bar -- `Context.request_context` is the
    documented v2 lifespan idiom -- which is why it is not in the table.
    """
    assert set(REMOVED_ATTRS) == {"get_context", "get_server_capabilities"}
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
    """The flagged client keywords are exactly the ones v1's `streamablehttp_client`
    accepted and v2's client does not: one it kept must not be flagged (a lie), and
    one it dropped must be (a silent `TypeError`). v1's signature is frozen history;
    v2's is introspected.
    """
    v1_parameters = frozenset(
        {"url", "headers", "timeout", "sse_read_timeout", "terminate_on_close", "httpx_client_factory", "auth"}
    )
    v2_parameters = frozenset(inspect.signature(streamable_http_client).parameters)
    assert v1_parameters - v2_parameters == TRANSPORT_CLIENT_REMOVED_PARAMS
