import base64
import binascii
import hmac
import time
from typing import Any
from urllib.parse import unquote

from starlette.requests import Request

from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.shared.auth import OAuthClientInformationFull


class AuthenticationError(Exception):
    def __init__(self, message: str):
        self.message = message


class ClientAuthenticator:
    """Validates client credentials on /token calls.

    A client that was issued a secret at registration must present that secret;
    clients that registered with no authentication skip this check.
    """

    def __init__(self, provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        self.provider = provider

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        """Validate the request's client credentials per the client's registered auth method.

        Raises:
            AuthenticationError: If authentication fails.
        """
        form_data = await request.form()
        client_id = form_data.get("client_id")
        if not client_id:
            raise AuthenticationError("Missing client_id")

        client = await self.provider.get_client(str(client_id))
        if not client:
            raise AuthenticationError("Invalid client_id")  # pragma: no cover

        request_client_secret: str | None = None
        auth_header = request.headers.get("Authorization", "")

        if client.token_endpoint_auth_method == "client_secret_basic":
            if not auth_header.startswith("Basic "):
                raise AuthenticationError("Missing or invalid Basic authentication in Authorization header")

            try:
                encoded_credentials = auth_header[6:]  # Remove "Basic " prefix
                decoded = base64.b64decode(encoded_credentials).decode("utf-8")
                if ":" not in decoded:
                    raise ValueError("Invalid Basic auth format")
                basic_client_id, request_client_secret = decoded.split(":", 1)

                # URL-decode both parts per RFC 6749 Section 2.3.1
                basic_client_id = unquote(basic_client_id)
                request_client_secret = unquote(request_client_secret)

                if basic_client_id != client_id:
                    raise AuthenticationError("Client ID mismatch in Basic auth")
            except (ValueError, UnicodeDecodeError, binascii.Error):
                raise AuthenticationError("Invalid Basic authentication header")

        elif client.token_endpoint_auth_method == "client_secret_post":
            raw_form_data = form_data.get("client_secret")
            # form_data.get() can return an UploadFile, not just str/None
            if isinstance(raw_form_data, str):
                request_client_secret = str(raw_form_data)

        elif client.token_endpoint_auth_method == "none":
            request_client_secret = None
        else:
            raise AuthenticationError(  # pragma: no cover
                f"Unsupported auth method: {client.token_endpoint_auth_method}"
            )

        # Secret-based auth method with no stored secret: nothing was verified above, so reject.
        if client.token_endpoint_auth_method != "none" and not client.client_secret:
            raise AuthenticationError("Client is registered for secret-based authentication but has no stored secret")

        if client.client_secret:
            if not request_client_secret:
                raise AuthenticationError("Client secret is required")

            # Encode to bytes: compare_digest requires bytes or ASCII-only str, and we don't control the input
            if not hmac.compare_digest(client.client_secret.encode(), request_client_secret.encode()):
                raise AuthenticationError("Invalid client_secret")

            if client.client_secret_expires_at and client.client_secret_expires_at < int(time.time()):
                raise AuthenticationError("Client secret has expired")  # pragma: no cover

        return client
