"""Tests for OAuth error handling in the auth handlers."""

import base64
import hashlib
import secrets
import unittest.mock
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from httpx2 import ASGITransport
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import AuthorizeError, RegistrationError, TokenError
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from tests.server.mcpserver.auth.test_auth_integration import MockOAuthProvider


@pytest.fixture
def oauth_provider():
    """Return a MockOAuthProvider instance that can be configured to raise errors."""
    return MockOAuthProvider()


@pytest.fixture
def app(oauth_provider: MockOAuthProvider):
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
def client(app: Starlette):
    transport = ASGITransport(app=app)
    # Use base_url without a path since routes are directly on the app
    return httpx2.AsyncClient(transport=transport, base_url="http://localhost")


@pytest.fixture
def pkce_challenge():
    """Create a PKCE challenge with code_verifier and code_challenge."""
    # Generate a code verifier
    code_verifier = secrets.token_urlsafe(64)[:128]

    # Create code challenge using S256 method
    code_verifier_bytes = code_verifier.encode("ascii")
    sha256 = hashlib.sha256(code_verifier_bytes).digest()
    code_challenge = base64.urlsafe_b64encode(sha256).decode().rstrip("=")

    return {"code_verifier": code_verifier, "code_challenge": code_challenge}


@pytest.fixture
async def registered_client(client: httpx2.AsyncClient) -> dict[str, Any]:
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


@pytest.mark.anyio
async def test_registration_error_handling(client: httpx2.AsyncClient, oauth_provider: MockOAuthProvider):
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


@pytest.mark.anyio
async def test_authorize_error_handling(
    client: httpx2.AsyncClient,
    oauth_provider: MockOAuthProvider,
    registered_client: dict[str, Any],
    pkce_challenge: dict[str, str],
):
    # Mock the authorize method to raise an authorize error
    with unittest.mock.patch.object(
        oauth_provider,
        "authorize",
        side_effect=AuthorizeError(error="access_denied", error_description="The user denied the request"),
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


@pytest.mark.anyio
async def test_token_error_handling_auth_code(
    client: httpx2.AsyncClient,
    oauth_provider: MockOAuthProvider,
    registered_client: dict[str, Any],
    pkce_challenge: dict[str, str],
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
    client: httpx2.AsyncClient,
    oauth_provider: MockOAuthProvider,
    registered_client: dict[str, Any],
    pkce_challenge: dict[str, str],
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


_FORM = "application/x-www-form-urlencoded"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path", "content_type"),
    [
        ("POST", "/token", _FORM),
        ("POST", "/revoke", _FORM),
        ("POST", "/register", "application/json"),
        ("POST", "/authorize", _FORM),
        # The other methods these routes accept reach the same body-reading handlers.
        ("OPTIONS", "/token", _FORM),
        ("OPTIONS", "/revoke", _FORM),
        ("OPTIONS", "/register", "application/json"),
        ("HEAD", "/authorize", _FORM),
    ],
)
async def test_oversized_request_body_returns_413(
    client: httpx2.AsyncClient, method: str, path: str, content_type: str
):
    """Each endpoint that reads a request body rejects one over 4 MiB before parsing it, whatever the method."""
    response = await client.request(
        method, path, content=b"x" * (DEFAULT_MAX_REQUEST_BODY_SIZE + 1), headers={"Content-Type": content_type}
    )
    assert response.status_code == 413


@pytest.mark.anyio
async def test_request_body_within_the_limit_is_still_parsed(client: httpx2.AsyncClient):
    """A small body is passed through to the handler intact: the form is parsed and its fields validated."""
    response = await client.post("/token", data={"grant_type": "authorization_code"})
    assert response.status_code == 401
    assert response.json() == {"error": "invalid_client", "error_description": "Missing client_id"}


@pytest.mark.anyio
async def test_cors_preflight_is_still_answered(client: httpx2.AsyncClient):
    """A CORS preflight to a body-limited endpoint is answered by the CORS layer as before."""
    response = await client.options(
        "/token", headers={"Origin": "https://client.example.com", "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


@pytest.mark.anyio
async def test_oversized_cross_origin_request_gets_413_with_cors_headers(client: httpx2.AsyncClient):
    """The 413 is produced inside the CORS layer, so a browser client can still read it."""
    response = await client.post(
        "/token",
        content=b"x" * (DEFAULT_MAX_REQUEST_BODY_SIZE + 1),
        headers={"Content-Type": _FORM, "Origin": "https://client.example.com"},
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "*"


async def _register(
    client: httpx2.AsyncClient,
    *,
    grant_types: list[str],
    token_endpoint_auth_method: str,
) -> dict[str, Any]:
    response = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "grant_types": grant_types,
            "response_types": ["code"],
            "client_name": "Test Client",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body


@pytest.mark.anyio
async def test_refresh_for_a_client_not_registered_for_it_is_unauthorized_client(client: httpx2.AsyncClient):
    """A grant this server implements, but this client is not registered for, is unauthorized_client.

    RFC 6749 §5.2 reserves unsupported_grant_type for a grant the authorization server
    itself does not implement.
    """
    registered = await _register(
        client, grant_types=["authorization_code"], token_endpoint_auth_method="client_secret_post"
    )
    client_id = registered["client_id"]
    client_secret = registered["client_secret"]
    assert isinstance(client_id, str)
    assert isinstance(client_secret, str)

    response = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "not-a-real-token",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )

    assert response.status_code == 400
    assert response.json() == snapshot(
        {
            "error": "unauthorized_client",
            "error_description": "The authenticated client is not authorized to use this authorization grant type",
        }
    )


@pytest.mark.anyio
@pytest.mark.parametrize("grant_type", ["client_credentials", "password", "not_a_grant"])
async def test_grant_the_server_does_not_implement_is_unsupported_grant_type(
    client: httpx2.AsyncClient, grant_type: str
):
    """A grant outside the set this server advertises is unsupported_grant_type, with no validation text.

    RFC 6749 §5.2. The code is chosen from grant_type before the request union is validated,
    so client_credentials and password do not surface as invalid_request.
    """
    registered = await _register(
        client, grant_types=["authorization_code"], token_endpoint_auth_method="client_secret_post"
    )
    client_id = registered["client_id"]
    client_secret = registered["client_secret"]
    assert isinstance(client_id, str)
    assert isinstance(client_secret, str)

    response = await client.post(
        "/token",
        data={"grant_type": grant_type, "client_id": client_id, "client_secret": client_secret},
    )

    assert response.status_code == 400
    assert response.json() == snapshot(
        {
            "error": "unsupported_grant_type",
            "error_description": "The authorization grant type is not supported by the authorization server",
        }
    )


@pytest.mark.anyio
async def test_authenticated_token_request_without_grant_type_is_invalid_request(client: httpx2.AsyncClient):
    """Omitting grant_type is a malformed request, so the code stays invalid_request.

    RFC 6749 §5.2: a missing required parameter is invalid_request. The description is
    pydantic's validation text, so only its presence is pinned.
    """
    registered = await _register(
        client,
        grant_types=["authorization_code", "refresh_token"],
        token_endpoint_auth_method="client_secret_post",
    )
    client_id = registered["client_id"]
    client_secret = registered["client_secret"]
    assert isinstance(client_id, str)
    assert isinstance(client_secret, str)

    response = await client.post("/token", data={"client_id": client_id, "client_secret": client_secret})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_request"
    assert body["error_description"]


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/token", "/revoke"])
async def test_failed_basic_authentication_includes_www_authenticate(client: httpx2.AsyncClient, path: str):
    """Failed HTTP Basic client authentication is 401 invalid_client with a Basic challenge.

    RFC 6749 §5.2 requires WWW-Authenticate matching the scheme the client used, and
    RFC 7617 §2 requires a realm on a Basic challenge. RFC 7009 §2.2.1 uses that same
    presentation for /revoke, so a bad secret there is invalid_client.
    """
    registered = await _register(
        client, grant_types=["authorization_code"], token_endpoint_auth_method="client_secret_basic"
    )
    client_id = registered["client_id"]
    assert isinstance(client_id, str)
    credentials = base64.b64encode(f"{client_id}:wrong".encode()).decode()

    response = await client.post(
        path,
        headers={"Authorization": f"Basic {credentials}"},
        data={"client_id": client_id, "grant_type": "refresh_token", "refresh_token": "rt", "token": "rt"},
    )

    assert response.status_code == 401
    assert response.json() == snapshot({"error": "invalid_client", "error_description": "Invalid client_secret"})
    assert response.headers["www-authenticate"] == 'Basic realm="OAuth"'


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/token", "/revoke"])
async def test_failed_client_secret_post_authentication_omits_www_authenticate(client: httpx2.AsyncClient, path: str):
    """A client_secret_post failure is invalid_client and carries no WWW-Authenticate header.

    RFC 6749 §5.2 requires that header only when the client used the Authorization field.
    /revoke uses the same code (RFC 7009 §2.2.1).
    """
    registered = await _register(
        client, grant_types=["authorization_code"], token_endpoint_auth_method="client_secret_post"
    )
    client_id = registered["client_id"]
    assert isinstance(client_id, str)

    response = await client.post(
        path,
        data={
            "client_id": client_id,
            "client_secret": "wrong",
            "grant_type": "refresh_token",
            "refresh_token": "rt",
            "token": "rt",
        },
    )

    assert response.status_code == 401
    assert response.json() == snapshot({"error": "invalid_client", "error_description": "Invalid client_secret"})
    assert "www-authenticate" not in response.headers
