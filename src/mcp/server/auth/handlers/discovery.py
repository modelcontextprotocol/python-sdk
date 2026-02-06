"""Unified authorization servers discovery handler (/.well-known/authorization_servers)."""

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.shared.auth import AuthProtocolMetadata


@dataclass
class AuthorizationServersDiscoveryHandler:
    """Handler for /.well-known/authorization_servers.

    Returns JSON with protocols (list of AuthProtocolMetadata), optional default_protocol,
    and optional protocol_preferences. Clients use "protocols" for discovery.
    """

    protocols: list[AuthProtocolMetadata]
    default_protocol: str | None = None
    protocol_preferences: dict[str, int] | None = None

    async def handle(self, request: Request) -> Response:
        content: dict[str, object] = {
            "protocols": [p.model_dump(mode="json", exclude_none=True) for p in self.protocols],
        }
        if self.default_protocol is not None:
            content["default_protocol"] = self.default_protocol
        if self.protocol_preferences is not None:
            content["protocol_preferences"] = self.protocol_preferences
        return JSONResponse(
            content,
            headers={"Cache-Control": "public, max-age=3600"},
        )
