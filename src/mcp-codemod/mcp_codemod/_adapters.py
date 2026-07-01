"""Emitted-source templates for the lowlevel decorator -> registration rewrite.

Adapters reproduce v1's wrapper semantics against the public v2 surface only: a
migrated file never imports from mcp_codemod, and nothing 2026-era is emitted.
Templates use `__FN__`/`__RECV__` placeholders instead of `str.format` because
the emitted code is full of braces.
"""

import ast
from dataclasses import dataclass, field

__all__ = ["LOWLEVEL_HANDLER_SPECS", "TEMPLATE_LOCALS", "HandlerSpec", "build_adapter", "cache_name", "handler_name"]

# Injected into the migrated module only when the name is not already bound by an import there.
ADAPTER_IMPORTS: dict[str, str] = {
    "base64": "import base64",
    "Iterable": "from collections.abc import Iterable",
    "cast": "from typing import cast",
    "json": "import json",
    "jsonschema": "import jsonschema",
    "AnyUrl": "from pydantic import AnyUrl",
    "MCPError": "from mcp import MCPError",
    "ServerRequestContext": "from mcp.server import ServerRequestContext",
    "ReadResourceContents": "from mcp.server.lowlevel.helper_types import ReadResourceContents",
    "mcp_types": "import mcp_types",
}


@dataclass(frozen=True, slots=True)
class HandlerSpec:
    """How one v1 decorator kind maps onto a generated v2 registration."""

    template: str
    arity: int
    """Positional-parameter count of the v1 handler signature."""
    imports: tuple[str, ...] = field(default=("ServerRequestContext", "mcp_types"))
    """Names from ADAPTER_IMPORTS the emitted code references."""
    notification: bool = False
    """Whether the kind registers through add_notification_handler."""


# v1's list wrappers passed an already-full result model through at runtime, so
# the adapter must too; the cast keeps the user's return annotation out of it.
_BARE_LIST = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.PaginatedRequestParams
) -> mcp_types.{result}:
    result = cast("object", await __FN__())
    if isinstance(result, mcp_types.{result}):
        return result
    return mcp_types.{result}({field}=cast("list[mcp_types.{item}]", result))


__RECV__.add_request_handler("{method}", mcp_types.PaginatedRequestParams, ___FN___handler)
"""

_GET_PROMPT = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.GetPromptRequestParams
) -> mcp_types.GetPromptResult:
    return await __FN__(params.name, params.arguments)


__RECV__.add_request_handler("prompts/get", mcp_types.GetPromptRequestParams, ___FN___handler)
"""

_COMPLETION = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.CompleteRequestParams
) -> mcp_types.CompleteResult:
    completion = await __FN__(params.ref, params.argument, params.context)
    if completion is None:
        completion = mcp_types.Completion(values=[], total=None, has_more=None)
    return mcp_types.CompleteResult(completion=completion)


__RECV__.add_request_handler("completion/complete", mcp_types.CompleteRequestParams, ___FN___handler)
"""

_URI_EMPTY = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.{params}
) -> mcp_types.EmptyResult:
    await __FN__(__URI__)
    return mcp_types.EmptyResult()


__RECV__.add_request_handler("{method}", mcp_types.{params}, ___FN___handler)
"""

_SET_LOGGING_LEVEL = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.SetLevelRequestParams
) -> mcp_types.EmptyResult:
    await __FN__(params.level)
    return mcp_types.EmptyResult()


__RECV__.add_request_handler("logging/setLevel", mcp_types.SetLevelRequestParams, ___FN___handler)
"""

_PROGRESS = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.ProgressNotificationParams
) -> None:
    await __FN__(params.progress_token, params.progress, params.total, params.message)


__RECV__.add_notification_handler("notifications/progress", mcp_types.ProgressNotificationParams, ___FN___handler)
"""

# Reproduces v1's `@read_resource()` return conversion: bare `str`/`bytes` is a single
# content item; iterables of `ReadResourceContents` convert with v1's default MIME types.
_READ_RESOURCE = """\

async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.ReadResourceRequestParams
) -> mcp_types.ReadResourceResult:
    result: object = await __FN__(__URI__)
    if isinstance(result, str | bytes):
        items = [ReadResourceContents(content=result)]
    else:
        items = list(cast("Iterable[ReadResourceContents]", result))
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents] = []
    for item in items:
        if isinstance(item.content, str):
            contents.append(
                mcp_types.TextResourceContents(
                    uri=params.uri, text=item.content, mime_type=item.mime_type or "text/plain", _meta=item.meta
                )
            )
        else:
            contents.append(
                mcp_types.BlobResourceContents(
                    uri=params.uri,
                    blob=base64.b64encode(item.content).decode(),
                    mime_type=item.mime_type or "application/octet-stream",
                    _meta=item.meta,
                )
            )
    return mcp_types.ReadResourceResult(contents=contents)


__RECV__.add_request_handler("resources/read", mcp_types.ReadResourceRequestParams, ___FN___handler)
"""

# Reproduces v1's `@call_tool()` dispatch in v1's order with v1's error strings, looking
# tools up through the registered tools/list handler; `MCPError` re-raises per v2's contract.
_CALL_TOOL = """\

___RECV___tool_cache: dict[str, mcp_types.Tool] = {}


async def ___FN___handler(
    ctx: ServerRequestContext, params: mcp_types.CallToolRequestParams
) -> mcp_types.CallToolResult:
    def _error(message: str) -> mcp_types.CallToolResult:
        return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=message)], is_error=True)

    try:
        arguments = params.arguments or {}
        if params.name not in ___RECV___tool_cache:
            listed = __RECV__.get_request_handler("tools/list")
            if listed is not None:
                tools = await listed.handler(ctx, mcp_types.PaginatedRequestParams())
                if isinstance(tools, mcp_types.ListToolsResult):
                    ___RECV___tool_cache.clear()
                    ___RECV___tool_cache.update({tool.name: tool for tool in tools.tools})
        tool = ___RECV___tool_cache.get(params.name)
__VALIDATION__        results = cast("object", await __FN__(params.name, arguments))
        if isinstance(results, mcp_types.CallToolResult):
            return results
        if isinstance(results, tuple) and len(results) == 2:
            content, structured = results
        elif isinstance(results, dict):
            content = [mcp_types.TextContent(type="text", text=json.dumps(results, indent=2))]
            structured = results
        elif isinstance(results, Iterable):
            content, structured = results, None
        else:
            return _error(f"Unexpected return type from tool: {type(results).__name__}")
        if tool is not None and tool.output_schema is not None:
            if structured is None:
                return _error("Output validation error: outputSchema defined but no structured output returned")
            try:
                jsonschema.validate(instance=structured, schema=tool.output_schema)
            except jsonschema.ValidationError as exc:
                return _error(f"Output validation error: {exc.message}")
        return mcp_types.CallToolResult(content=list(content), structured_content=structured, is_error=False)
    except MCPError:
        raise
    except Exception as exc:
        return _error(str(exc))


__RECV__.add_request_handler("tools/call", mcp_types.CallToolRequestParams, ___FN___handler)
"""

_CALL_TOOL_VALIDATION = """\
        if tool is not None:
            try:
                jsonschema.validate(instance=arguments, schema=tool.input_schema)
            except jsonschema.ValidationError as exc:
                return _error(f"Input validation error: {exc.message}")
"""

_URI_IMPORTS = ("ServerRequestContext", "mcp_types")

LOWLEVEL_HANDLER_SPECS: dict[str, HandlerSpec] = {
    "list_tools": HandlerSpec(
        _BARE_LIST.format(result="ListToolsResult", field="tools", method="tools/list", item="Tool"),
        0,
        ("ServerRequestContext", "mcp_types", "cast"),
    ),
    "list_resources": HandlerSpec(
        _BARE_LIST.format(result="ListResourcesResult", field="resources", method="resources/list", item="Resource"),
        0,
        ("ServerRequestContext", "mcp_types", "cast"),
    ),
    "list_prompts": HandlerSpec(
        _BARE_LIST.format(result="ListPromptsResult", field="prompts", method="prompts/list", item="Prompt"),
        0,
        ("ServerRequestContext", "mcp_types", "cast"),
    ),
    "list_resource_templates": HandlerSpec(
        _BARE_LIST.format(
            result="ListResourceTemplatesResult",
            field="resource_templates",
            method="resources/templates/list",
            item="ResourceTemplate",
        ),
        0,
        ("ServerRequestContext", "mcp_types", "cast"),
    ),
    "get_prompt": HandlerSpec(_GET_PROMPT, 2),
    "completion": HandlerSpec(_COMPLETION, 3),
    "subscribe_resource": HandlerSpec(
        _URI_EMPTY.format(params="SubscribeRequestParams", method="resources/subscribe"), 1, _URI_IMPORTS
    ),
    "unsubscribe_resource": HandlerSpec(
        _URI_EMPTY.format(params="UnsubscribeRequestParams", method="resources/unsubscribe"), 1, _URI_IMPORTS
    ),
    "set_logging_level": HandlerSpec(_SET_LOGGING_LEVEL, 1),
    "progress_notification": HandlerSpec(_PROGRESS, 4, notification=True),
    "read_resource": HandlerSpec(
        _READ_RESOURCE,
        1,
        ("ServerRequestContext", "mcp_types", "ReadResourceContents", "Iterable", "cast", "base64"),
    ),
    "call_tool": HandlerSpec(
        _CALL_TOOL, 2, ("ServerRequestContext", "mcp_types", "MCPError", "Iterable", "cast", "json", "jsonschema")
    ),
}


def handler_name(fn: str) -> str:
    """The emitted adapter's name for a handler function."""
    return f"_{fn}_handler"


def cache_name(recv: str) -> str:
    """The emitted call_tool tool-cache name for a server variable."""
    return f"_{recv}_tool_cache"


def _template_locals() -> dict[str, frozenset[str]]:
    """Names each rendered template binds, derived from the templates themselves.

    A user function sharing one of these names would be shadowed inside its own
    adapter (UnboundLocalError), so the transformer blocks those sites.
    """
    locals_by_kind: dict[str, frozenset[str]] = {}
    for kind in LOWLEVEL_HANDLER_SPECS:
        names: set[str] = set()
        for node in ast.walk(ast.parse(build_adapter(kind, "no_fn", "no_recv"))):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
        locals_by_kind[kind] = frozenset(names)
    return locals_by_kind


def build_adapter(kind: str, fn: str, recv: str, *, validate_input: bool = True, uri_as_str: bool = False) -> str:
    """Render the emitted block for one rewritten decorator site.

    `validate_input=False` omits only the input-validation block -- v1 validated output
    schemas regardless. `uri_as_str` passes the wire string through for `str`-annotated uris.
    """
    template = LOWLEVEL_HANDLER_SPECS[kind].template
    template = template.replace("__VALIDATION__", _CALL_TOOL_VALIDATION if validate_input else "")
    template = template.replace("__URI__", "params.uri" if uri_as_str else "AnyUrl(params.uri)")
    return template.replace("__FN__", fn).replace("__RECV__", recv)


TEMPLATE_LOCALS: dict[str, frozenset[str]] = _template_locals()
