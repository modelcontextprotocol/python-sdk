"""OAuth token verifier using introspection (PRM-only variant reuses same logic)."""

import logging
from typing import Any, cast

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

logger = logging.getLogger(__name__)


class IntrospectionTokenVerifier(TokenVerifier):
    """Verify Bearer tokens via OAuth 2.0 Token Introspection (RFC 7662)."""

    def __init__(
        self,
        introspection_endpoint: str,
        server_url: str,
        validate_resource: bool = False,
    ):
        self.introspection_endpoint = introspection_endpoint
        self.server_url = server_url
        self.validate_resource = validate_resource
        self.resource_url = resource_url_from_server_url(server_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token via introspection endpoint."""
        import httpx

        if not self.introspection_endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            logger.warning("Rejecting unsafe introspection endpoint")
            return None

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            try:
                response = await client.post(
                    self.introspection_endpoint,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if response.status_code != 200:
                    return None
                data = response.json()
                if not data.get("active", False):
                    return None
                if self.validate_resource and not self._validate_resource(data):
                    return None
                return AccessToken(
                    token=token,
                    client_id=data.get("client_id", "unknown"),
                    scopes=data.get("scope", "").split() if data.get("scope") else [],
                    expires_at=data.get("exp"),
                    resource=data.get("aud"),
                )
            except Exception as e:
                logger.warning("Token introspection failed: %s", e)
                return None

    def _validate_resource(self, token_data: dict[str, Any]) -> bool:
        if not self.server_url or not self.resource_url:
            return False
        aud = token_data.get("aud")
        if isinstance(aud, list):
            for item in cast(list[str], aud):
                if self._is_valid_resource(item):
                    return True
            return False
        if isinstance(aud, str):
            return self._is_valid_resource(aud)
        return False

    def _is_valid_resource(self, resource: str) -> bool:
        if not self.resource_url:
            return False
        return check_resource_allowed(requested_resource=self.resource_url, configured_resource=resource)
