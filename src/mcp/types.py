"""Deprecated: the protocol types moved to the standalone `mcp_types` package.

`import mcp.types` still works in v2 as a compatibility shim, but it emits an
`MCPDeprecationWarning` and will be removed in v3. Import from `mcp_types` instead:

    from mcp_types import Tool, TextContent

Field names also changed from camelCase to snake_case (`tool.input_schema`, not
`tool.inputSchema`), so an import that succeeds through this shim can still fail
later on attribute access. See the migration guide, "Types and wire format".
"""

# A wildcard mirror of the mcp_types namespace is the whole point of this shim.
# pyright: reportWildcardImportFromLibrary=false

import warnings

from mcp_types import *
from mcp_types import __all__ as __all__

from mcp.shared.exceptions import MCPDeprecationWarning

warnings.warn(
    "mcp.types is deprecated; import from mcp_types. Fields are now snake_case; see the migration guide.",
    MCPDeprecationWarning,
    stacklevel=2,
)

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
        # ImportError, not AttributeError: `from mcp.types import X` swallows an
        # AttributeError raised here and reports a generic "cannot import name",
        # discarding the hint; an ImportError propagates through both the
        # from-import and plain attribute-access paths with the message intact.
        raise ImportError(f"mcp.types.{name} was removed in v2; {hint}. See the migration guide.")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
