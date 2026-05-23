"""Shared type aliases for the interaction suite.

Keep this module small: it exists only for types that every test would otherwise have to
assemble from the SDK's internals to annotate a client callback. Server fixtures and assertion
helpers belong in the test that uses them.
"""

from mcp.shared.session import RequestResponder
from mcp.types import ClientResult, ServerNotification, ServerRequest

# TODO: this union is the parameter type of every client message handler (MessageHandlerFnT),
# but the SDK does not export a name for it -- writing a correctly-typed handler requires
# importing RequestResponder from mcp.shared.session and assembling the union by hand. It
# should be a named, exported alias next to MessageHandlerFnT (like ClientRequestContext is
# for the request callbacks), at which point this module can be deleted.
IncomingMessage = RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception
"""Everything a client message handler can receive."""
