"""The v1 -> v2 rename and removal tables.

Every transform in `_transformer.py` is driven by one of these tables, and
`tests/codemod/test_mappings.py` pins them against the installed v2 packages.
"""

import re
from typing import Literal, NamedTuple

__all__ = [
    "CAMEL_FIELDS",
    "ERRORDATA_QNAMES",
    "FASTMCP_QNAMES",
    "CLIENT_SESSION_QNAMES",
    "LOWLEVEL_CTOR_POSITIONAL_PARAMS",
    "LOWLEVEL_REMOVED_ATTRS",
    "LOWLEVEL_SERVER_QNAMES",
    "MCPERROR_QNAMES",
    "PYDANTIC_URL_QNAMES",
    "SESSION_LIST_METHODS",
    "SESSION_URI_METHODS",
    "TIMEDELTA_QNAMES",
    "UNION_TYPE_ALIASES",
    "MODULE_RENAMES",
    "REHOMED_IMPORTS",
    "REMOVED_APIS",
    "REMOVED_ATTRS",
    "REMOVED_CTOR_PARAMS",
    "REMOVED_EXTRAS",
    "REMOVED_MODULES",
    "SYMBOL_RENAMES",
    "TRANSPORT_CLIENT_QNAMES",
    "TRANSPORT_CLIENT_REMOVED_PARAMS",
    "TRANSPORT_CLIENT_V1_QNAMES",
    "TRANSPORT_CTOR_PARAMS",
    "CamelField",
]

# Module-path renames, applied by longest prefix to imports and fully-dotted usages.
MODULE_RENAMES: dict[str, str] = {
    "mcp.server.fastmcp": "mcp.server.mcpserver",
    "mcp.server.fastmcp.server": "mcp.server.mcpserver.server",
    "mcp.shared.version": "mcp_types.version",
    "mcp.types": "mcp_types",
}

# (renamed module, imported name) -> the name's PUBLIC v2 home, applied after
# `MODULE_RENAMES`: a type checker treats a name a module does not re-export as private.
REHOMED_IMPORTS: dict[tuple[str, str], str] = {
    ("mcp.server.mcpserver.server", "Context"): "mcp.server.mcpserver",
}

# v1 module roots with no v2 home under any name, matched by longest prefix. Imports
# are marked, never rewritten; with `MODULE_RENAMES` these cover every public v1 module.
REMOVED_MODULES: dict[str, str] = {
    "mcp.client.experimental": ("removed: the v1 experimental tasks API was deleted and has no replacement"),
    "mcp.server.experimental": ("removed: the v1 experimental tasks API was deleted and has no replacement"),
    "mcp.server.lowlevel.experimental": ("removed: the v1 experimental tasks API was deleted and has no replacement"),
    "mcp.shared.experimental": ("removed: the v1 experimental tasks API was deleted and has no replacement"),
    "mcp.client.websocket": "removed: the WebSocket transport was deleted",
    "mcp.server.websocket": "removed: the WebSocket transport was deleted",
    "mcp.server.lowlevel.func_inspection": "removed: it was an internal helper of the lowlevel server",
    "mcp.shared.progress": "removed: report progress with `ctx.report_progress()` inside a handler",
    "mcp.shared.response_router": "removed: it was internal session machinery; there is no public replacement",
}

# Symbol renames, keyed by every v1 qualified name the symbol was reachable from.
# Usages resolve through the file's imports, so aliases and same-named user symbols are safe.
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

# v1 public symbols with no v2 home: never rewritten, a `# mcp-codemod:` marker carries the guidance.
REMOVED_APIS: dict[str, str] = {
    "mcp.shared.memory.create_connected_server_and_client_session": (
        "removed: pair `create_client_server_memory_streams()` with `Server.run()` and a `ClientSession` "
        "to keep the v1 test shape, or use `mcp.Client(server)`"
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
    "mcp.shared.session.BaseSession": "removed: use `ClientSession` or `ServerSession` directly",
    "mcp.server.lowlevel.server.request_ctx": (
        "removed: the module-level ContextVar is gone; handlers now receive `ctx` explicitly"
    ),
    # Every v1 `mcp.types` name with no same-name home in `mcp_types`. Enumerating
    # them all is what lets the tests prove every other rewritten import resolves.
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
    "mcp.types.TaskExecutionMode": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_REQUIRED": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_OPTIONAL": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_FORBIDDEN": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_STATUS_WORKING": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_STATUS_INPUT_REQUIRED": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_STATUS_COMPLETED": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_STATUS_FAILED": "removed with the v1 experimental tasks API",
    "mcp.types.TASK_STATUS_CANCELLED": "removed with the v1 experimental tasks API",
}

# Extras the v1 `mcp` distribution declared that v2 does not.
REMOVED_EXTRAS: dict[str, str] = {
    "ws": "the `ws` extra was removed with the WebSocket transport",
}

# Removed attributes matched by NAME only (receiver types are unknown): an entry must be
# distinctive AND not spelled by any surviving v2 API (see `LOWLEVEL_REMOVED_ATTRS`).
REMOVED_ATTRS: dict[str, str] = {
    "get_context": "`MCPServer.get_context()` was removed: accept a `ctx: Context` parameter on the handler instead",
    "get_server_capabilities": "removed: read `session.initialize_result` instead",
    "_mcp_server": "renamed on v2: the wrapped lowlevel server is the private `_lowlevel_server` attribute",
}


class CamelField(NamedTuple):
    """The v2 fate of one camelCase field name declared in v1's `mcp/types.py`."""

    snake: str
    tier: Literal["safe", "risky"]


def _to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# camelCase names whose rename still needs human eyes: generic enough to exist on a
# non-mcp object in the same file, or with a v1 home whose v2 shape is not a rename
# (`params.meta.progressToken` needs a `params.meta["progress_token"]` subscript).
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

# Every camelCase field name declared in v1's `mcp/types.py`. Names outside this set
# are never renamed, keeping stdlib, third-party, and user camelCase attributes untouched.
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

# `MCPServer.__init__` kwargs that moved to `run()` / the app factories. The right
# destination depends on how the server is started, so the kwarg is only marked and
# left in place (v2 fails loudly): deleting it would silently lose configuration.
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

# v1 lowlevel `Server.__init__` parameters after `name`, in positional order; v2 keeps
# the names but makes them keyword-only, so positional arguments convert one for one.
LOWLEVEL_CTOR_POSITIONAL_PARAMS: tuple[str, ...] = ("version", "instructions", "website_url", "icons", "lifespan")

# Removed lowlevel `Server` attributes whose NAMES survive elsewhere on v2, so they
# only match receivers the pre-pass proved are lowlevel servers.
LOWLEVEL_REMOVED_ATTRS: dict[str, str] = {
    "request_context": (
        "`Server.request_context` and the `request_ctx` ContextVar were removed: handlers now receive `ctx` explicitly"
    ),
    "request_handlers": (
        "the type-keyed `request_handlers` dict was replaced: register with "
        "`add_request_handler(method, params_type, handler)` and look up with `get_request_handler(method)`"
    ),
    "notification_handlers": (
        "the type-keyed `notification_handlers` dict was replaced: register with "
        "`add_notification_handler(method, params_type, handler)`"
    ),
}

# Qualified-name sets the transformer resolves callees and constructors against;
# the renamed-class sets are derived from `SYMBOL_RENAMES` so they cannot drift from it.
FASTMCP_QNAMES: frozenset[str] = frozenset(old for old, new in SYMBOL_RENAMES.items() if new == "MCPServer")
MCPERROR_QNAMES: frozenset[str] = frozenset(old for old, new in SYMBOL_RENAMES.items() if new == "MCPError")
LOWLEVEL_SERVER_QNAMES: frozenset[str] = frozenset(
    {
        "mcp.server.Server",
        "mcp.server.lowlevel.Server",
        "mcp.server.lowlevel.server.Server",
    }
)
CLIENT_SESSION_QNAMES: frozenset[str] = frozenset(
    {
        "mcp.ClientSession",
        "mcp.client.ClientSession",
        "mcp.client.session.ClientSession",
    }
)
TIMEDELTA_QNAMES: frozenset[str] = frozenset({"datetime.timedelta"})
PYDANTIC_URL_QNAMES: frozenset[str] = frozenset(
    {
        "pydantic.AnyUrl",
        "pydantic.FileUrl",
        "pydantic.networks.AnyUrl",
        "pydantic.networks.FileUrl",
    }
)
# `ClientSession` methods whose v1 `cursor=` keyword became `params=PaginatedRequestParams(...)`.
SESSION_LIST_METHODS: frozenset[str] = frozenset(
    {"list_tools", "list_prompts", "list_resources", "list_resource_templates"}
)
# `ClientSession` methods whose `uri` parameter is a plain `str` on v2 (was `AnyUrl`).
SESSION_URI_METHODS: frozenset[str] = frozenset({"read_resource", "subscribe_resource", "unsubscribe_resource"})

# v1 RootModel wrappers that are plain union aliases on v2: the import is fine, but
# constructing them or calling pydantic model methods fails, so only those uses are marked.
UNION_TYPE_ALIASES: dict[str, str] = {
    "mcp.types.ClientNotification": "ClientNotification",
    "mcp.types.ClientRequest": "ClientRequest",
    "mcp.types.ClientResult": "ClientResult",
    "mcp.types.JSONRPCMessage": "JSONRPCMessage",
    "mcp.types.ServerNotification": "ServerNotification",
    "mcp.types.ServerRequest": "ServerRequest",
    "mcp.types.ServerResult": "ServerResult",
}

ERRORDATA_QNAMES: frozenset[str] = frozenset(
    {
        "mcp.ErrorData",
        "mcp.types.ErrorData",
    }
)
# The streamable-HTTP client's v1 qualified names, and the same set widened with the
# v2 spelling: a half-migrated call under the v2 name still gets the 3-tuple rewrite,
# but only a v1-NAME call proves unmigrated code, so only it is flagged for the yield shape.
TRANSPORT_CLIENT_V1_QNAMES: frozenset[str] = frozenset(
    old for old, new in SYMBOL_RENAMES.items() if new == "streamable_http_client"
)
TRANSPORT_CLIENT_QNAMES: frozenset[str] = TRANSPORT_CLIENT_V1_QNAMES | {
    "mcp.client.streamable_http.streamable_http_client"
}
# v1 `streamablehttp_client` keywords that v2 dropped; `terminate_on_close` survived.
TRANSPORT_CLIENT_REMOVED_PARAMS: frozenset[str] = frozenset(
    {"auth", "headers", "httpx_client_factory", "sse_read_timeout", "timeout"}
)
