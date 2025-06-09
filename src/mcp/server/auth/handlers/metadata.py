from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.shared.auth import OAuthMetadata, OAuthProtectedResourceMetadata


@dataclass
class MetadataHandler:
    metadata: OAuthMetadata | OAuthProtectedResourceMetadata

    async def handle(self, request: Request) -> Response:
        return PydanticJSONResponse(
            content=self.metadata,
            headers={"Cache-Control": "public, max-age=3600"},  # Cache for 1 hour
        )
