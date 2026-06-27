"""The v1 -> v2 rename and removal tables.

These tables are the single source of truth for what the codemod does. Every
transform in `_transformer.py` is driven by one of them; nothing is pattern-matched
by name alone. Each entry was derived by comparing `origin/v1.x` against `main`
in this repository, and the camelCase table is additionally pinned against the
installed `mcp_types` package by `tests/codemod/test_mappings.py`, so it cannot
silently drift as v2 evolves.
"""

import re
from typing import Literal, NamedTuple

__all__ = [
    "CAMEL_FIELDS",
    "ERRORDATA_QNAMES",
    "FASTMCP_QNAMES",
    "LOWLEVEL_DECORATOR_METHODS",
    "LOWLEVEL_SERVER_QNAMES",
    "MCPERROR_QNAMES",
    "MODULE_RENAMES",
    "REMOVED_APIS",
    "REMOVED_ATTRS",
    "REMOVED_CTOR_PARAMS",
    "SYMBOL_RENAMES",
    "TRANSPORT_CLIENT_QNAMES",
    "TRANSPORT_CLIENT_REMOVED_PARAMS",
    "TRANSPORT_CLIENT_V1_QNAMES",
    "TRANSPORT_CTOR_PARAMS",
    "CamelField",
]

# Module-path renames, applied by longest prefix to `import X` / `from X import ...`
# statements and to fully-dotted usages such as `mcp.types.Tool`. Every right side
# must be importable on v2, and `tests/codemod/test_mappings.py` further pins that
# the public names of each old module are all importable from the new one (or are
# themselves renamed or removed), so a rewritten import always resolves.
MODULE_RENAMES: dict[str, str] = {
    "mcp.server.fastmcp": "mcp.server.mcpserver",
    "mcp.server.fastmcp.server": "mcp.server.mcpserver.server",
    "mcp.shared.version": "mcp_types.version",
    "mcp.types": "mcp_types",
}

# Symbol renames, keyed by every v1 qualified name the symbol was reachable from.
# The transformer resolves a usage to its qualified name through the file's imports
# (`libcst.metadata.QualifiedNameProvider`), so an aliased import is never broken
# and a user's own symbol that happens to share a name is never touched.
SYMBOL_RENAMES: dict[str, str] = {
    "mcp.server.FastMCP": "MCPServer",
    "mcp.server.fastmcp.FastMCP": "MCPServer",
    "mcp.server.fastmcp.server.FastMCP": "MCPServer",
    "mcp.server.fastmcp.exceptions.FastMCPError": "MCPServerError",
    "mcp.McpError": "MCPError",
    "mcp.shared.exceptions.McpError": "MCPError",
    "mcp.client.streamable_http.streamablehttp_client": "streamable_http_client",
    # Removed v1 aliases whose real names survive on v2.
    "mcp.types.Content": "ContentBlock",
    "mcp.types.ResourceReference": "ResourceTemplateReference",
}

# v1 public symbols that no longer exist on v2 under any name. The codemod never
# rewrites these (there is nothing correct to rewrite them to); it inserts a
# `# mcp-codemod:` marker carrying the replacement guidance.
REMOVED_APIS: dict[str, str] = {
    "mcp.shared.memory.create_connected_server_and_client_session": (
        "removed: connect an in-memory pair with `mcp.Client(server)` instead"
    ),
    "mcp.shared.progress.progress": "removed: report progress with `ctx.report_progress()` inside a handler",
    "mcp.shared.progress.Progress": "removed: `mcp.shared.progress` was deleted",
    "mcp.shared.progress.ProgressContext": "removed: `mcp.shared.progress` was deleted",
    "mcp.client.websocket.websocket_client": "removed: the WebSocket transport was deleted",
    "mcp.server.websocket.websocket_server": "removed: the WebSocket transport was deleted",
    "mcp.shared.context.RequestContext": (
        "split: use `mcp.server.context.ServerRequestContext` or `mcp.client.context.ClientRequestContext`"
    ),
    "mcp.os.win32.utilities.terminate_windows_process": "removed",
    "mcp.shared.session.BaseSession": "removed: sessions now run on `JSONRPCDispatcher`",
    "mcp.server.lowlevel.server.request_ctx": (
        "removed: the module-level ContextVar is gone; handlers now receive `ctx` explicitly"
    ),
    # The v1 `mcp.types` names with no same-name home in `mcp_types`. The task
    # vocabulary collapsed into the literal strings on v2 and the rest were v1
    # type-machinery aliases. Enumerating every one is what keeps the
    # `mcp.types` -> `mcp_types` rewrite honest: `tests/codemod/test_mappings.py`
    # checks that every other public v1 name resolves on `mcp_types`, so an
    # import this codemod produces is never one that cannot be imported.
    "mcp.types.Cursor": "removed: it was an alias of `str`; use `str`",
    # A nested class, so the per-name module check in the tests cannot see it.
    "mcp.types.RequestParams.Meta": (
        "removed: request metadata is the `RequestParamsMeta` TypedDict on v2, keyed by snake_case names"
    ),
    "mcp.types.AnyFunction": "removed: it was an alias of `Callable[..., Any]`",
    "mcp.types.MethodT": "removed: the generic request type parameters are gone",
    "mcp.types.RequestParamsT": "removed: the generic request type parameters are gone",
    "mcp.types.NotificationParamsT": "removed: the generic request type parameters are gone",
    "mcp.types.ClientRequestType": "removed: use the `ClientRequest` union",
    "mcp.types.ClientNotificationType": "removed: use the `ClientNotification` union",
    "mcp.types.ClientResultType": "removed: use the `ClientResult` union",
    "mcp.types.ServerRequestType": "removed: use the `ServerRequest` union",
    "mcp.types.ServerNotificationType": "removed: use the `ServerNotification` union",
    "mcp.types.ServerResultType": "removed: use the `ServerResult` union",
    "mcp.types.TaskExecutionMode": "removed: `ToolExecution.task_support` takes the literal string on v2",
    "mcp.types.TASK_REQUIRED": 'removed: use the literal string `"required"`',
    "mcp.types.TASK_OPTIONAL": 'removed: use the literal string `"optional"`',
    "mcp.types.TASK_FORBIDDEN": 'removed: use the literal string `"forbidden"`',
    "mcp.types.TASK_STATUS_WORKING": 'removed: use the literal string `"working"`',
    "mcp.types.TASK_STATUS_INPUT_REQUIRED": 'removed: use the literal string `"input_required"`',
    "mcp.types.TASK_STATUS_COMPLETED": 'removed: use the literal string `"completed"`',
    "mcp.types.TASK_STATUS_FAILED": 'removed: use the literal string `"failed"`',
    "mcp.types.TASK_STATUS_CANCELLED": 'removed: use the literal string `"cancelled"`',
}

# Attribute and method names that vanished from a class that still exists. These
# can only be matched by name (the codemod cannot know a receiver's type), so a
# name qualifies only when it is distinctive enough that a false match is
# implausible AND no surviving v2 API spells it. The lowlevel
# `Server.request_context` property fails the second bar -- `Context.request_context`
# is a live, documented v2 idiom -- so its removal is deliberately not flagged here.
REMOVED_ATTRS: dict[str, str] = {
    "get_context": "`MCPServer.get_context()` was removed: accept a `ctx: Context` parameter on the handler instead",
    "get_server_capabilities": "removed: read `session.initialize_result` instead",
}


class CamelField(NamedTuple):
    """The v2 fate of one camelCase field name declared in v1's `mcp/types.py`."""

    snake: str
    tier: Literal["safe", "risky"]


def _to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# The camelCase field names a "safe" attribute rewrite needs human eyes on anyway.
# Two reasons land a name here: it is generic enough to plausibly exist on a
# non-mcp object in the same file (`createdAt`, `requestId`, `mimeType`, ...), or
# the v1 field also lived somewhere whose v2 home is NOT a renamed attribute.
# `progressToken` is the canonical second case: `ProgressNotificationParams`
# renamed it to `progress_token`, but v1's `RequestParams.Meta` model became the
# `RequestParamsMeta` TypedDict, so `params.meta.progressToken` needs a subscript
# (`params.meta["progress_token"]`), not a rename. Safe-tier renames are reported;
# risky-tier renames are reported AND get an inline `# mcp-codemod: review:` marker.
_RISKY: frozenset[str] = frozenset(
    {
        "createdAt",
        "elicitationId",
        "hasMore",
        "isError",
        "lastUpdatedAt",
        "maxTokens",
        "mimeType",
        "nextCursor",
        "pollInterval",
        "progressToken",
        "requestId",
        "statusMessage",
        "stopReason",
        "stopSequences",
        "taskId",
        "toolUseId",
        "websiteUrl",
    }
)

# Every camelCase field name declared in v1's `mcp/types.py`. Anything outside
# this set is never renamed -- this is what keeps `logging.getLogger`, stdlib and
# third-party camelCase APIs, and the user's own attributes untouched.
_V1_CAMEL_FIELDS: tuple[str, ...] = (
    "clientInfo",
    "costPriority",
    "createMessage",
    "createdAt",
    "destructiveHint",
    "elicitationId",
    "hasMore",
    "idempotentHint",
    "includeContext",
    "inputSchema",
    "intelligencePriority",
    "isError",
    "lastUpdatedAt",
    "listChanged",
    "maxTokens",
    "mimeType",
    "modelPreferences",
    "nextCursor",
    "openWorldHint",
    "outputSchema",
    "pollInterval",
    "progressToken",
    "protocolVersion",
    "readOnlyHint",
    "requestId",
    "requestedSchema",
    "resourceTemplates",
    "serverInfo",
    "speedPriority",
    "statusMessage",
    "stopReason",
    "stopSequences",
    "structuredContent",
    "systemPrompt",
    "taskId",
    "taskSupport",
    "toolChoice",
    "toolUseId",
    "uriTemplate",
    "websiteUrl",
)

CAMEL_FIELDS: dict[str, CamelField] = {
    name: CamelField(_to_snake(name), "risky" if name in _RISKY else "safe") for name in _V1_CAMEL_FIELDS
}

# `MCPServer.__init__` keyword arguments that moved to `run()` / `sse_app()` /
# `streamable_http_app()`. The right destination depends on how the server is
# started, and may not be in the same file, so these are never rewritten: the
# kwarg is left in place (v2 then fails loudly with a `TypeError`) and a marker
# is inserted. Deleting the kwarg instead would silently lose configuration.
TRANSPORT_CTOR_PARAMS: frozenset[str] = frozenset(
    {
        "event_store",
        "host",
        "json_response",
        "message_path",
        "port",
        "retry_interval",
        "sse_path",
        "stateless_http",
        "streamable_http_path",
        "transport_security",
    }
)

# `MCPServer.__init__` keyword arguments removed outright on v2.
REMOVED_CTOR_PARAMS: dict[str, str] = {
    "mount_path": "removed: mount the app under a Starlette route instead",
}

# The v1 lowlevel `Server` decorator-factory methods and the `on_*` keyword each
# became on the v2 `Server` constructor. This transform is flag-only by design:
# moving the registration means reordering statements across the module AND
# rewriting the handler to `(ctx, params) -> Result` with no return auto-wrapping,
# and a codemod that guesses at that loses more trust than it saves time.
LOWLEVEL_DECORATOR_METHODS: dict[str, str] = {
    "call_tool": "on_call_tool",
    "completion": "on_completion",
    "get_prompt": "on_get_prompt",
    "list_prompts": "on_list_prompts",
    "list_resource_templates": "on_list_resource_templates",
    "list_resources": "on_list_resources",
    "list_tools": "on_list_tools",
    "progress_notification": "on_progress",
    "read_resource": "on_read_resource",
    "set_logging_level": "on_set_logging_level",
    "subscribe_resource": "on_subscribe_resource",
    "unsubscribe_resource": "on_unsubscribe_resource",
}

# Qualified-name sets the transformer resolves callees and constructors against.
# The two that name renamed classes are DERIVED from `SYMBOL_RENAMES` rather than
# written out, so a v1 import path added there can never be silently missing here.
FASTMCP_QNAMES: frozenset[str] = frozenset(old for old, new in SYMBOL_RENAMES.items() if new == "MCPServer")
MCPERROR_QNAMES: frozenset[str] = frozenset(old for old, new in SYMBOL_RENAMES.items() if new == "MCPError")
LOWLEVEL_SERVER_QNAMES: frozenset[str] = frozenset(
    {
        "mcp.server.Server",
        "mcp.server.lowlevel.Server",
        "mcp.server.lowlevel.server.Server",
    }
)
ERRORDATA_QNAMES: frozenset[str] = frozenset(
    {
        "mcp.ErrorData",
        "mcp.types.ErrorData",
    }
)
# The v1 qualified names of the streamable-HTTP client (derived, like the class
# sets above), and the same set widened with the v2 spelling. A half-migrated
# `streamable_http_client(...) as (read, write, _)` still deserves the 3-tuple
# rewrite, but only a call through the v1 NAME proves the surrounding code is
# unmigrated, so only that form is flagged for its changed yield shape.
TRANSPORT_CLIENT_V1_QNAMES: frozenset[str] = frozenset(
    old for old, new in SYMBOL_RENAMES.items() if new == "streamable_http_client"
)
TRANSPORT_CLIENT_QNAMES: frozenset[str] = TRANSPORT_CLIENT_V1_QNAMES | {
    "mcp.client.streamable_http.streamable_http_client"
}
# Every keyword v1's `streamablehttp_client` accepted that v2's does not -- the
# whole point of `http_client=`. `terminate_on_close` survived and is not here.
TRANSPORT_CLIENT_REMOVED_PARAMS: frozenset[str] = frozenset(
    {"auth", "headers", "httpx_client_factory", "sse_read_timeout", "timeout"}
)
