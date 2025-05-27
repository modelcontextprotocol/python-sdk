"""
Tests for OAuth error handling in the auth handlers.
"""

import unittest.mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import ASGITransport
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import (
    AuthorizeError,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.routes import create_auth_routes
from tests.server.fastmcp.auth.test_auth_integration import (
    MockOAuthProvider,
)


@pytest.fixture
def oauth_provider():
    """Return a MockOAuthProvider instance that can be configured to raise errors."""
    return MockOAuthProvider()


@pytest.fixture
def app(oauth_provider):
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions

    # Enable client registration
    client_registration_options = ClientRegistrationOptions(enabled=True)
    revocation_options = RevocationOptions(enabled=True)

    # Create auth routes
    auth_routes = create_auth_routes(
        oauth_provider,
        issuer_url=AnyHttpUrl("http://localhost"),
        client_registration_options=client_registration_options,
        revocation_options=revocation_options,
    )

    # Create Starlette app with routes directly
    return Starlette(routes=auth_routes)


@pytest.fixture
def client(app):
    transport = ASGITransport(app=app)
    # Use base_url without a path since routes are directly on the app
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


@pytest.fixture
def pkce_challenge():
    """Create a PKCE challenge with code_verifier and code_challenge."""
    import base64
    import hashlib
    import secrets

    # Generate a code verifier
    code_verifier = secrets.token_urlsafe(64)[:128]

    # Create code challenge using S256 method
    code_verifier_bytes = code_verifier.encode("ascii")
    sha256 = hashlib.sha256(code_verifier_bytes).digest()
    code_challenge = base64.urlsafe_b64encode(sha256).decode().rstrip("=")

    return {"code_verifier": code_verifier, "code_challenge": code_challenge}


@pytest.fixture
async def registered_client(client):
    """Create and register a test client."""
    # Default client metadata
    client_metadata = {
        "redirect_uris": ["https://client.example.com/callback"],
        "token_endpoint_auth_method": "client_secret_post",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "Test Client",
    }

    response = await client.post("/register", json=client_metadata)
    assert response.status_code == 201, f"Failed to register client: {response.content}"

    client_info = response.json()
    return client_info


class TestRegistrationErrorHandling:
    @pytest.mark.anyio
    async def test_registration_error_handling(self, client, oauth_provider):
        # Mock the register_client method to raise a registration error
        with unittest.mock.patch.object(
            oauth_provider,
            "register_client",
            side_effect=RegistrationError(
                error="invalid_redirect_uri",
                error_description="The redirect URI is invalid",
            ),
        ):
            # Prepare a client registration request
            client_data = {
                "redirect_uris": ["https://client.example.com/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "Test Client",
            }

            # Send the registration request
            response = await client.post(
                "/register",
                json=client_data,
            )

            # Verify the response
            assert response.status_code == 400, response.content
            data = response.json()
            assert data["error"] == "invalid_redirect_uri"
            assert data["error_description"] == "The redirect URI is invalid"


class TestAuthorizeErrorHandling:
    @pytest.mark.anyio
    async def test_authorize_error_handling(
        self, client, oauth_provider, registered_client, pkce_challenge
    ):
        # Mock the authorize method to raise an authorize error
        with unittest.mock.patch.object(
            oauth_provider,
            "authorize",
            side_effect=AuthorizeError(
                error="access_denied", error_description="The user denied the request"
            ),
        ):
            # Register the client
            client_id = registered_client["client_id"]
            redirect_uri = registered_client["redirect_uris"][0]

            # Prepare an authorization request
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            }

            # Send the authorization request
            response = await client.get("/authorize", params=params)

            # Verify the response is a redirect with error parameters
            assert response.status_code == 302
            redirect_url = response.headers["location"]
            parsed_url = urlparse(redirect_url)
            query_params = parse_qs(parsed_url.query)

            assert query_params["error"][0] == "access_denied"
            assert "error_description" in query_params
            assert query_params["state"][0] == "test_state"


class TestTokenErrorHandling:
    @pytest.mark.anyio
    async def test_token_error_handling_auth_code(
        self, client, oauth_provider, registered_client, pkce_challenge
    ):
        # Register the client and get an auth code
        client_id = registered_client["client_id"]
        client_secret = registered_client["client_secret"]
        redirect_uri = registered_client["redirect_uris"][0]

        # First get an authorization code
        auth_response = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        redirect_url = auth_response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)
        code = query_params["code"][0]

        # Mock the exchange_authorization_code method to raise a token error
        with unittest.mock.patch.object(
            oauth_provider,
            "exchange_authorization_code",
            side_effect=TokenError(
                error="invalid_grant",
                error_description="The authorization code is invalid",
            ),
        ):
            # Try to exchange the code for tokens
            token_response = await client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": pkce_challenge["code_verifier"],
                },
            )

            # Verify the response
            assert token_response.status_code == 400
            data = token_response.json()
            assert data["error"] == "invalid_grant"
            assert data["error_description"] == "The authorization code is invalid"

    @pytest.mark.anyio
    async def test_token_error_handling_refresh_token(
        self, client, oauth_provider, registered_client, pkce_challenge
    ):
        # Register the client and get tokens
        client_id = registered_client["client_id"]
        client_secret = registered_client["client_secret"]
        redirect_uri = registered_client["redirect_uris"][0]

        # First get an authorization code
        auth_response = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )
        assert auth_response.status_code == 302, auth_response.content

        redirect_url = auth_response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)
        code = query_params["code"][0]

        # Exchange the code for tokens
        token_response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": pkce_challenge["code_verifier"],
            },
        )

        tokens = token_response.json()
        refresh_token = tokens["refresh_token"]

        # Mock the exchange_refresh_token method to raise a token error
        with unittest.mock.patch.object(
            oauth_provider,
            "exchange_refresh_token",
            side_effect=TokenError(
                error="invalid_scope",
                error_description="The requested scope is invalid",
            ),
        ):
            # Try to use the refresh token
            refresh_response = await client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )

            # Verify the response
            assert refresh_response.status_code == 400
            data = refresh_response.json()
            assert data["error"] == "invalid_scope"
            assert data["error_description"] == "The requested scope is invalid"
