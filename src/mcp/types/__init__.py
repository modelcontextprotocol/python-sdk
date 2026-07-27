"""The MCP protocol wire types, as the `mcp.types` namespace.

This module mirrors the standalone `mcp_types` package exactly (every name is the
same object), so SDK users can keep the familiar v1 spelling:

    import mcp.types as types

    types.TextContent(type="text", text="hi")

The protocol-version registry lives in the `mcp.types.version` submodule,
mirroring `mcp_types.version` the same way.

Depend on and import `mcp_types` directly instead when you only need to
(de)serialize MCP traffic and don't want the SDK's transport stack: its only
runtime dependencies are `pydantic` and `typing-extensions`.
"""

# A wildcard mirror of the mcp_types namespace is the whole point of this module.
# pyright: reportWildcardImportFromLibrary=false

from mcp_types import *
from mcp_types import __all__ as __all__

# Names v1's mcp.types exposed that no longer exist. A bare "cannot import name"
# leaves people grepping; naming the replacement finishes the migration step.
_REMOVED = {
    "Content": "use ContentBlock",
    "ResourceReference": "use ResourceTemplateReference",
    "Cursor": "use str",
    "AnyFunction": "use Callable[..., Any]",
    "MethodT": "it was an internal TypeVar, not public API",
    "RequestParamsT": "it was an internal TypeVar, not public API",
    "NotificationParamsT": "it was an internal TypeVar, not public API",
    "ClientRequestType": "the union is now the bare name ClientRequest",
    "ClientNotificationType": "the union is now the bare name ClientNotification",
    "ClientResultType": "the union is now the bare name ClientResult",
    "ServerRequestType": "the union is now the bare name ServerRequest",
    "ServerNotificationType": "the union is now the bare name ServerNotification",
    "ServerResultType": "the union is now the bare name ServerResult",
    "TaskExecutionMode": "use the string literals directly",
    "TASK_FORBIDDEN": "use the string literal 'forbidden'",
    "TASK_OPTIONAL": "use the string literal 'optional'",
    "TASK_REQUIRED": "use the string literal 'required'",
    "TASK_STATUS_CANCELLED": "use the string literal 'cancelled'; TaskStatus remains",
    "TASK_STATUS_COMPLETED": "use the string literal 'completed'; TaskStatus remains",
    "TASK_STATUS_FAILED": "use the string literal 'failed'; TaskStatus remains",
    "TASK_STATUS_INPUT_REQUIRED": "use the string literal 'input_required'; TaskStatus remains",
    "TASK_STATUS_WORKING": "use the string literal 'working'; TaskStatus remains",
}


def __getattr__(name: str) -> object:
    if (hint := _REMOVED.get(name)) is not None:
        # AttributeError as PEP 562 requires, so hasattr() and getattr(..., default)
        # still take their fallback path. The cost: `from mcp.types import Content`
        # discards this message for CPython's generic "cannot import name" (still
        # fail-fast); attribute access, the far more common v1 spelling, keeps it.
        raise AttributeError(f"mcp.types.{name} was removed in v2; {hint}. See the migration guide.")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
