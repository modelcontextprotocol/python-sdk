"""Example token verifier implementation using OAuth 2.0 Token Introspection (RFC 7662)."""

from datetime import datetime
import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.shared.auth_utils import resource_url_from_server_url

logger = logging.getLogger(__name__)


class IntrospectionTokenVerifier(TokenVerifier):
    """Example token verifier that uses OAuth 2.0 Token Introspection (RFC 7662).
    """

    def __init__(
        self,
        introspection_endpoint: str,
        server_url: str,
    ):
        self.introspection_endpoint = introspection_endpoint
        self.server_url = server_url
        self.resource_url = resource_url_from_server_url(server_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token via introspection endpoint."""
        import httpx

        # Validate URL to prevent SSRF attacks
        if not self.introspection_endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            logger.warning(f"Rejecting introspection endpoint with unsafe scheme: {self.introspection_endpoint}")
            return None

        # Configure secure HTTP client
        timeout = httpx.Timeout(10.0, connect=5.0)
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)

        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            verify=True,  # Enforce SSL verification
            headers={
                "Authorization": f"Bearer {token}",
            },
        ) as client:
            try:
                response = await client.get(
                    self.introspection_endpoint,
                )

                if response.status_code != 200:
                    logger.debug(f"Token introspection returned status {response.status_code}")
                    return None

                data = response.json()
                return AccessToken(
                    token=token,
                    client_id=data.get("application", {"id": "unknown"}).get("id", "unknown"),
                    scopes=data.get("scopes", "") if data.get("scopes") else [],
                    expires_at=int(datetime.fromisoformat(data.get("expires")).timestamp()),
                )
            except Exception as e:
                logger.warning(f"Token introspection failed: {e}")
                return None
