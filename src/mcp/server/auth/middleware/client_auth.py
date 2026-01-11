import base64
import binascii
import hmac
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote

from starlette.requests import Request

from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.shared.auth import OAuthClientInformationFull


class AuthenticationError(Exception):
    def __init__(self, message: str):
        self.message = message  # pragma: no cover


@dataclass
class ClientCredentials:
    auth_method: Literal["client_secret_basic", "client_secret_post"]
    client_id: str
    client_secret: str | None = None


class ClientAuthenticator:
    """
    ClientAuthenticator is a callable which validates requests from a client
    application, used to verify /token calls.
    If, during registration, the client requested to be issued a secret, the
    authenticator asserts that /token calls must be authenticated with
    that same token.
    NOTE: clients can opt for no authentication during registration, in which case this
    logic is skipped.
    """

    def __init__(self, provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        """
        Initialize the dependency.

        Args:
            provider: Provider to look up client information
        """
        self.provider = provider

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        """
        Authenticate a client from an HTTP request.

        Extracts client credentials from the appropriate location based on the
        client's registered authentication method and validates them.

        Args:
            request: The HTTP request containing client credentials

        Returns:
            The authenticated client information

        Raises:
            AuthenticationError: If authentication fails
        """
        client_credentials = await self._get_credentials(request)
        client = await self.provider.get_client(str(client_credentials.client_id))
        if not client:
            raise AuthenticationError("Invalid client_id")  # pragma: no cover

        match client.token_endpoint_auth_method:
            case "client_secret_basic":
                if client_credentials.auth_method != "client_secret_basic":
                    raise AuthenticationError(f"Expected client_secret_basic authentication method, but got {client_credentials.auth_method}")
            case "client_secret_post":
                if client_credentials.auth_method != "client_secret_post":
                    raise AuthenticationError(f"Expected client_secret_post authentication method, but got {client_credentials.auth_method}")
            case "none":
                pass
            case _:
                raise AuthenticationError(f"Unsupported auth method: {client.token_endpoint_auth_method}")  # pragma: no cover

        # If client from the store expects a secret, validate that the request provides
        # that secret
        if client.client_secret:  # pragma: no branch
            if not client_credentials.client_secret:
                raise AuthenticationError("Client secret is required")  # pragma: no cover

            # hmac.compare_digest requires that both arguments are either bytes or a `str` containing
            # only ASCII characters. Since we do not control `request_client_secret`, we encode both
            # arguments to bytes.
            if not hmac.compare_digest(client.client_secret.encode(), client_credentials.client_secret.encode()):
                raise AuthenticationError("Invalid client_secret")  # pragma: no cover

            if client.client_secret_expires_at and client.client_secret_expires_at < int(time.time()):
                raise AuthenticationError("Client secret has expired")  # pragma: no cover

        return client

    async def _get_credentials(self, request: Request) -> ClientCredentials:
        """
        Extract client credentials from request, either from form data or Basic auth header.
        
        Basic auth header takes precedence over form data.
        
        Args:
            request: The HTTP request containing client credentials
        Returns:
            The extracted client credentials
        """
        # First, check for Basic auth header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                encoded_credentials = auth_header[6:]  # Remove "Basic " prefix
                decoded = base64.b64decode(encoded_credentials).decode("utf-8")
                if ":" not in decoded:
                    raise ValueError("Invalid Basic auth format")
                client_id, client_secret = decoded.split(":", 1)

                # URL-decode the client_id per RFC 6749 Section 2.3.1
                client_id = unquote(client_id)
                client_secret = unquote(client_secret)
                return ClientCredentials(
                    auth_method="client_secret_basic",
                    client_id=client_id,
                    client_secret=client_secret,
                )
            except (ValueError, UnicodeDecodeError, binascii.Error):
                raise AuthenticationError("Invalid Basic authentication header")

        # If not, check for client_id and client_secret in form data
        form_data = await request.form()
        client_id = form_data.get("client_id")
        if not client_id:
            raise AuthenticationError("Missing client_id")
        
        raw_client_secret = form_data.get("client_secret")
        client_secret = str(raw_client_secret) if isinstance(raw_client_secret, str) else None
        return ClientCredentials(
            auth_method="client_secret_post",
            client_id=str(client_id),
            client_secret=client_secret,
        )
