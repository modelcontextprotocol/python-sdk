"""Pin the codemod's mapping tables against the installed v2 package.

The tables in `mcp_codemod._mappings` drive every rewrite the tool makes, so each
one is held to two bars here: an exact literal so a silently-deleted row can never
shrink the suite, and a check against the installed `mcp` / `mcp_types` packages
so a rename target or a removal claim cannot drift as v2 evolves. A failure here
means the table is wrong, not the transformer.
"""

import inspect
from importlib import import_module
from importlib.metadata import metadata
from importlib.util import find_spec

import mcp_types
import pytest
from mcp_codemod import transform
from mcp_codemod._mappings import (
    CAMEL_FIELDS,
    LOWLEVEL_CTOR_POSITIONAL_PARAMS,
    LOWLEVEL_DECORATOR_METHODS,
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


# Every public module v1 shipped (no path segment starting with an underscore),
# extracted from `origin/v1.x` and frozen here because v1 is closed history.
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
    """The whole v1 module namespace is accounted for: every public module either
    still imports on v2, is rewritten by `MODULE_RENAMES`, or is marked through a
    `REMOVED_MODULES` root. An unaccounted module would mean an import the codemod
    neither fixes nor flags. The removed roots must also really be gone from v2,
    and each must cover at least one v1 module (no stale roots).
    """

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
    """The flagged extras are exactly the ones v1's `mcp` distribution declared and
    the installed v2 does not: flagging a surviving extra would be a lie, and
    missing a removed one leaves a constraint that cannot resolve. v1's set is
    frozen history; v2's comes from the installed metadata.
    """
    v1_extras = {"cli", "rich", "ws"}
    v2_extras = set(metadata("mcp").get_all("Provides-Extra") or [])
    assert v1_extras - v2_extras == set(REMOVED_EXTRAS)


def test_every_rehomed_import_points_at_a_declared_public_export() -> None:
    """A rehome target must spell the name in its `__all__` -- the whole point is
    moving the import to where v2 declares the name publicly -- and the source
    module must still hold the name too, so the rehome is never load-bearing
    for runtime behaviour.
    """
    for (source_module, name), target in REHOMED_IMPORTS.items():
        assert name in getattr(import_module(target), "__all__", []), (source_module, name)
        assert hasattr(import_module(source_module), name), (source_module, name)


def test_every_lowlevel_removed_attribute_is_really_gone_from_the_v2_server() -> None:
    """The receiver-matched lowlevel removals must be absent from the v2 `Server`
    (a marker on a live attribute would be a lie), while still being spelled by
    some other living v2 API -- otherwise the plain name-matched `REMOVED_ATTRS`
    table is their cheaper home.
    """
    assert set(LOWLEVEL_REMOVED_ATTRS) == {"request_context"}
    for name in LOWLEVEL_REMOVED_ATTRS:
        assert not hasattr(Server, name), name
        assert hasattr(Context, name), name


def test_the_lowlevel_positional_params_are_keyword_only_on_the_installed_server() -> None:
    """Every v1 positional the codemod converts must exist, keyword-only, on the
    installed v2 `Server.__init__` -- otherwise the conversion emits a `TypeError`."""
    parameters = inspect.signature(Server.__init__).parameters
    for name in LOWLEVEL_CTOR_POSITIONAL_PARAMS:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
