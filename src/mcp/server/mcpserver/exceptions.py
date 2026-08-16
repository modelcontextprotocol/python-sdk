"""Custom exceptions for MCPServer."""


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ResourceError(MCPServerError):
    """Error in resource operations.

    When a resource or resource template handler raises this, its message reaches
    the client as a `-32603` protocol error.
    """


class ResourceNotFoundError(ResourceError):
    """Resource does not exist.

    Raise this from a resource handler to signal that the requested instance does not exist.
    Clients receive `-32602` (invalid params) per
    [SEP-2164](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164).
    """


class UnexpectedResourceError(ResourceError):
    """A resource read failed with something other than `ResourceError` or `MCPError`.

    MCPServer raises this itself, around a crash in a resource or resource
    template handler or a failed file read. You never raise it. `__cause__` is
    the original exception, which the server logs with its traceback. The
    message names only the URI, so the original text is withheld from the client.
    """


class ToolError(MCPServerError):
    """A tool failure the model should read.

    Raise this from a tool (or a resolver) for a failure you anticipate: the
    call returns `is_error=True` with the message in `content`, and the server
    logs it at INFO without a traceback. Any other exception reaches the model
    the same way but is treated as a crash and logged at ERROR with its traceback.

    The SDK raises it too, for an unknown tool name and for arguments that fail
    the input schema, and `UnexpectedToolError` subclasses it, so `except ToolError`
    around `MCPServer.call_tool()` catches every tool failure, crash or not.
    """


class UnexpectedToolError(ToolError):
    """A tool call failed with something other than `ToolError` or `MCPError`.

    MCPServer raises this itself, around a crash in the tool (or a resolver) or a
    return value that fails output conversion. You never raise it. `__cause__` is
    the original exception, which the server logs with its traceback before
    returning the usual `is_error=True` result. Catch it around
    `MCPServer.call_tool()` to tell a crash from a deliberate `ToolError`.
    """


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
