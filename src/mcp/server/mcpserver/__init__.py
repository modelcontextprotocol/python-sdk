"""MCPServer - A more ergonomic interface for MCP servers."""

from mcp_types import Icon

from mcp.server.extension import Extension, MethodBinding, ResourceBinding, ToolBinding
from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateBoundary,
    RequestStateCodec,
    RequestStateSecurity,
    authenticated_principal,
)

from .context import Context
from .resolve import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from .resources import DEFAULT_RESOURCE_SECURITY, ResourceSecurity
from .server import MCPServer, require_client_extension
from .utilities.types import Audio, Image

__all__ = [
    "MCPServer",
    "Context",
    "Image",
    "Audio",
    "Icon",
    "Resolve",
    "Elicit",
    "ElicitationResult",
    "AcceptedElicitation",
    "DeclinedElicitation",
    "CancelledElicitation",
    "Extension",
    "ToolBinding",
    "ResourceBinding",
    "MethodBinding",
    "require_client_extension",
    "ResourceSecurity",
    "DEFAULT_RESOURCE_SECURITY",
    "RequestStateSecurity",
    "RequestStateCodec",
    "RequestStateBoundary",
    "AESGCMRequestStateCodec",
    "InvalidRequestState",
    "authenticated_principal",
]
