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
    ListRoots,
    Resolve,
    Sample,
)
from .resources import DEFAULT_RESOURCE_SECURITY, ResourceSecurity
from .server import MCPServer, require_client_extension
from .utilities.types import Audio, Image

__all__ = [
    "DEFAULT_RESOURCE_SECURITY",
    "AESGCMRequestStateCodec",
    "AcceptedElicitation",
    "Audio",
    "CancelledElicitation",
    "Context",
    "DeclinedElicitation",
    "Elicit",
    "ElicitationResult",
    "Extension",
    "Icon",
    "Image",
    "InvalidRequestState",
    "ListRoots",
    "MCPServer",
    "MethodBinding",
    "RequestStateBoundary",
    "RequestStateCodec",
    "RequestStateSecurity",
    "Resolve",
    "ResourceBinding",
    "ResourceSecurity",
    "Sample",
    "ToolBinding",
    "authenticated_principal",
    "require_client_extension",
]
