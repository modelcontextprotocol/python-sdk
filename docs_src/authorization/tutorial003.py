import secrets
from dataclasses import dataclass

from mcp.server import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.transport import TransportContext


@dataclass(kw_only=True, frozen=True)
class VerifiedPeer(TransportContext):
    principal: str


def principal(ctx: ServerRequestContext) -> str:
    if not isinstance(ctx.transport, VerifiedPeer):
        raise ValueError("Verified transport identity is required")
    return ctx.transport.principal


mcp = MCPServer(
    "broker-service",
    request_state_security=RequestStateSecurity(
        keys=[secrets.token_bytes(32)],
        bind_principal=principal,
    ),
)
