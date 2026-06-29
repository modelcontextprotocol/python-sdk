"""Integration tests for MCP authorization components."""

import base64
import hashlib
import secrets
import time
import unittest.mock
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import AnyHttpUrl, AnyUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class MockOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self):
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, str] = {}  # refresh_token -> access_token

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        assert client_info.client_id is not None
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # Toy implementation: skips user interaction, immediately issues a code and redirects.
        assert client.client_id is not None
        code = AuthorizationCode(
            code=f"code_{int(time.time())}",
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            expires_at=time.time() + 300,
            scopes=params.scopes or ["read", "write"],
            subject="test-user",
        )
        self.auth_codes[code.code] = code

        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        assert authorization_code.code in self.auth_codes

        access_token = f"access_{secrets.token_hex(32)}"
        refresh_token = f"refresh_{secrets.token_hex(32)}"

        assert client.client_id is not None
        self.tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 3600,
            subject=authorization_code.subject,
        )

        self.refresh_tokens[refresh_token] = access_token

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            scope="read write",
            refresh_token=refresh_token,
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        old_access_token = self.refresh_tokens.get(refresh_token)
        if old_access_token is None:
            return None
        token_info = self.tokens.get(old_access_token)
        if token_info is None:  # pragma: no cover
            return None

        refresh_obj = RefreshToken(
            token=refresh_token,
            client_id=token_info.client_id,
            scopes=token_info.scopes,
            expires_at=token_info.expires_at,
            subject=token_info.subject,
        )

        return refresh_obj

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        assert refresh_token.token in self.refresh_tokens

        old_access_token = self.refresh_tokens[refresh_token.token]

        assert old_access_token in self.tokens

        token_info = self.tokens[old_access_token]
        assert token_info.client_id == client.client_id

        new_access_token = f"access_{secrets.token_hex(32)}"
        new_refresh_token = f"refresh_{secrets.token_hex(32)}"

        assert client.client_id is not None
        self.tokens[new_access_token] = AccessToken(
            token=new_access_token,
            client_id=client.client_id,
            scopes=scopes or token_info.scopes,
            expires_at=int(time.time()) + 3600,
            subject=refresh_token.subject,
        )

        self.refresh_tokens[new_refresh_token] = new_access_token

        del self.refresh_tokens[refresh_token.token]
        del self.tokens[old_access_token]

        return OAuthToken(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes) if scopes else " ".join(token_info.scopes),
            refresh_token=new_refresh_token,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        token_info = self.tokens.get(token)

        return token_info and AccessToken(
            token=token,
            client_id=token_info.client_id,
            scopes=token_info.scopes,
            expires_at=token_info.expires_at,
            subject=token_info.subject,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        match token:
            case RefreshToken():  # pragma: lax no cover
                del self.refresh_tokens[token.token]

            case AccessToken():  # pragma: no branch
                del self.tokens[token.token]

                for refresh_token, access_token in list(self.refresh_tokens.items()):
                    if access_token == token.token:  # pragma: no branch
                        del self.refresh_tokens[refresh_token]


@pytest.fixture
def mock_oauth_provider():
    return MockOAuthProvider()


@pytest.fixture
def auth_app(mock_oauth_provider: MockOAuthProvider):
    auth_routes = create_auth_routes(
        mock_oauth_provider,
        AnyHttpUrl("https://auth.example.com"),
        AnyHttpUrl("https://docs.example.com"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["read", "write", "profile"],
            default_scopes=["read", "write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )

    app = Starlette(routes=auth_routes)

    return app


@pytest.fixture
async def test_client(auth_app: Starlette):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=auth_app), base_url="https://mcptest.com") as client:
        yield client


@pytest.fixture
async def registered_client(
    test_client: httpx.AsyncClient, request: pytest.FixtureRequest
) -> OAuthClientInformationFull:
    """Register a test client; override metadata via indirect parameterization."""
    client_metadata = {
        "redirect_uris": ["https://client.example.com/callback"],
        "client_name": "Test Client",
        "grant_types": ["authorization_code", "refresh_token"],
    }

    if hasattr(request, "param") and request.param:
        client_metadata.update(request.param)

    response = await test_client.post("/register", json=client_metadata)
    assert response.status_code == 201, f"Failed to register client: {response.content}"

    client_info = response.json()
    return client_info


@pytest.fixture
def pkce_challenge():
    code_verifier = "some_random_verifier_string"
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")

    return {"code_verifier": code_verifier, "code_challenge": code_challenge}


@pytest.fixture
async def auth_code(
    test_client: httpx.AsyncClient,
    registered_client: dict[str, Any],
    pkce_challenge: dict[str, str],
    request: pytest.FixtureRequest,
):
    """Obtain an authorization code; override authorize params via indirect parameterization."""
    auth_params = {
        "response_type": "code",
        "client_id": registered_client["client_id"],
        "redirect_uri": "https://client.example.com/callback",
        "code_challenge": pkce_challenge["code_challenge"],
        "code_challenge_method": "S256",
        "state": "test_state",
    }

    if hasattr(request, "param") and request.param:  # pragma: no cover
        auth_params.update(request.param)

    response = await test_client.get("/authorize", params=auth_params)
    assert response.status_code == 302, f"Failed to get auth code: {response.content}"

    redirect_url = response.headers["location"]
    parsed_url = urlparse(redirect_url)
    query_params = parse_qs(parsed_url.query)

    assert "code" in query_params, f"No code in response: {query_params}"
    auth_code = query_params["code"][0]

    return {
        "code": auth_code,
        "redirect_uri": auth_params["redirect_uri"],
        "state": query_params.get("state", [None])[0],
    }


class TestAuthEndpoints:
    @pytest.mark.anyio
    async def test_metadata_endpoint(self, test_client: httpx.AsyncClient):
        response = await test_client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200

        metadata = response.json()
        assert metadata["issuer"] == "https://auth.example.com/"
        assert metadata["authorization_endpoint"] == "https://auth.example.com/authorize"
        assert metadata["token_endpoint"] == "https://auth.example.com/token"
        assert metadata["registration_endpoint"] == "https://auth.example.com/register"
        assert metadata["revocation_endpoint"] == "https://auth.example.com/revoke"
        assert metadata["response_types_supported"] == ["code"]
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert metadata["token_endpoint_auth_methods_supported"] == ["client_secret_post", "client_secret_basic"]
        assert metadata["grant_types_supported"] == [
            "authorization_code",
            "refresh_token",
        ]
        assert metadata["service_documentation"] == "https://docs.example.com/"

    @pytest.mark.anyio
    async def test_token_validation_error(self, test_client: httpx.AsyncClient):
        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                # Missing code, code_verifier, client_id, etc.
            },
        )
        error_response = response.json()
        # RFC 6749 section 5.2: missing client_id is "invalid_client", not "unauthorized_client"
        assert error_response["error"] == "invalid_client"
        assert "error_description" in error_response

    @pytest.mark.anyio
    async def test_token_invalid_client_secret_returns_invalid_client(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        pkce_challenge: dict[str, str],
        mock_oauth_provider: MockOAuthProvider,
    ):
        """RFC 6749 section 5.2: a wrong client_secret is an authentication failure (`invalid_client`)."""
        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=registered_client["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": "wrong_secret_that_does_not_match",
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )

        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Invalid client_secret" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_invalid_auth_code(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        pkce_challenge: dict[str, str],
    ):
        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "code": "non_existent_auth_code",
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )

        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_grant"
        assert "authorization code does not exist" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_expired_auth_code(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        auth_code: dict[str, str],
        pkce_challenge: dict[str, str],
        mock_oauth_provider: MockOAuthProvider,
    ):
        current_time = time.time()

        code_value = auth_code["code"]
        found_code = None
        for code_obj in mock_oauth_provider.auth_codes.values():  # pragma: no branch
            if code_obj.code == code_value:  # pragma: no branch
                found_code = code_obj
                break

        assert found_code is not None

        # Codes expire after 300s; mock time 600s ahead.
        with unittest.mock.patch("time.time", return_value=current_time + 600):
            response = await test_client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": registered_client["client_id"],
                    "client_secret": registered_client["client_secret"],
                    "code": code_value,
                    "code_verifier": pkce_challenge["code_verifier"],
                    "redirect_uri": auth_code["redirect_uri"],
                },
            )
            assert response.status_code == 400
            error_response = response.json()
            assert error_response["error"] == "invalid_grant"
            assert "authorization code has expired" in error_response["error_description"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "registered_client",
        [
            {
                "redirect_uris": [
                    "https://client.example.com/callback",
                    "https://client.example.com/other-callback",
                ]
            }
        ],
        indirect=True,
    )
    async def test_token_redirect_uri_mismatch(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        auth_code: dict[str, str],
        pkce_challenge: dict[str, str],
    ):
        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "code": auth_code["code"],
                "code_verifier": pkce_challenge["code_verifier"],
                # Different from the one used in /authorize
                "redirect_uri": "https://client.example.com/other-callback",
            },
        )
        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_request"
        assert "redirect_uri did not match" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_code_verifier_mismatch(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], auth_code: dict[str, str]
    ):
        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "code": auth_code["code"],
                "code_verifier": "incorrect_code_verifier",
                "redirect_uri": auth_code["redirect_uri"],
            },
        )
        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_grant"
        assert "incorrect code_verifier" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_invalid_refresh_token(self, test_client: httpx.AsyncClient, registered_client: dict[str, Any]):
        response = await test_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "refresh_token": "non_existent_refresh_token",
            },
        )
        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_grant"
        assert "refresh token does not exist" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_expired_refresh_token(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        auth_code: dict[str, str],
        pkce_challenge: dict[str, str],
    ):
        current_time = time.time()

        token_response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "code": auth_code["code"],
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": auth_code["redirect_uri"],
            },
        )
        assert token_response.status_code == 200
        tokens = token_response.json()
        refresh_token = tokens["refresh_token"]

        # Tokens expire in 1 hour; mock time 4 hours ahead.
        with unittest.mock.patch("time.time", return_value=current_time + 14400):
            response = await test_client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": registered_client["client_id"],
                    "client_secret": registered_client["client_secret"],
                    "refresh_token": refresh_token,
                },
            )

            assert response.status_code == 400
            error_response = response.json()
            assert error_response["error"] == "invalid_grant"
            assert "refresh token has expired" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_token_invalid_scope(
        self,
        test_client: httpx.AsyncClient,
        registered_client: dict[str, Any],
        auth_code: dict[str, str],
        pkce_challenge: dict[str, str],
    ):
        token_response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "code": auth_code["code"],
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": auth_code["redirect_uri"],
            },
        )
        assert token_response.status_code == 200

        tokens = token_response.json()
        refresh_token = tokens["refresh_token"]

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "refresh_token": refresh_token,
                "scope": "read write invalid_scope",
            },
        )
        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_scope"
        assert "cannot request scope" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_client_registration(self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "client_uri": "https://client.example.com",
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 201, response.content

        client_info = response.json()
        assert "client_id" in client_info
        assert "client_secret" in client_info
        assert client_info["client_name"] == "Test Client"
        assert client_info["redirect_uris"] == ["https://client.example.com/callback"]

    @pytest.mark.anyio
    async def test_client_registration_missing_required_fields(self, test_client: httpx.AsyncClient):
        # Missing redirect_uris, which is required
        client_metadata = {
            "client_name": "Test Client",
            "client_uri": "https://client.example.com",
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert error_data["error_description"] == "redirect_uris: Field required"

    @pytest.mark.anyio
    async def test_client_registration_invalid_uri(self, test_client: httpx.AsyncClient):
        client_metadata = {
            "redirect_uris": ["not-a-valid-uri"],
            "client_name": "Test Client",
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert error_data["error_description"] == (
            "redirect_uris.0: Input should be a valid URL, relative URL without a base"
        )

    @pytest.mark.anyio
    async def test_client_registration_empty_redirect_uris(self, test_client: httpx.AsyncClient):
        redirect_uris: list[str] = []
        client_metadata = {
            "redirect_uris": redirect_uris,
            "client_name": "Test Client",
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert (
            error_data["error_description"] == "redirect_uris: List should have at least 1 item after validation, not 0"
        )

    @pytest.mark.anyio
    async def test_authorize_form_post(self, test_client: httpx.AsyncClient, pkce_challenge: dict[str, str]):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 201
        client_info = response.json()

        response = await test_client.post(
            "/authorize",
            data={
                "response_type": "code",
                "client_id": client_info["client_id"],
                "redirect_uri": "https://client.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_form_state",
            },
        )
        assert response.status_code == 302

        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "code" in query_params
        assert query_params["state"][0] == "test_form_state"

    @pytest.mark.anyio
    async def test_authorization_get(
        self,
        test_client: httpx.AsyncClient,
        mock_oauth_provider: MockOAuthProvider,
        pkce_challenge: dict[str, str],
    ):
        """Full flow: register, authorize via GET, exchange code, verify, refresh, revoke."""
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post(
            "/register",
            json=client_metadata,
        )
        assert response.status_code == 201
        client_info = response.json()

        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_info["client_id"],
                "redirect_uri": "https://client.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )
        assert response.status_code == 302

        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "code" in query_params
        assert query_params["state"][0] == "test_state"
        auth_code = query_params["code"][0]

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 200

        token_response = response.json()
        assert "access_token" in token_response
        assert "token_type" in token_response
        assert "refresh_token" in token_response
        assert "expires_in" in token_response
        assert token_response["token_type"] == "Bearer"

        access_token = token_response["access_token"]
        refresh_token = token_response["refresh_token"]

        auth_info = await mock_oauth_provider.load_access_token(access_token)
        assert auth_info
        assert auth_info.client_id == client_info["client_id"]
        assert "read" in auth_info.scopes
        assert "write" in auth_info.scopes
        assert auth_info.subject == "test-user"

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "refresh_token": refresh_token,
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 200

        new_token_response = response.json()
        assert "access_token" in new_token_response
        assert "refresh_token" in new_token_response
        assert new_token_response["access_token"] != access_token
        assert new_token_response["refresh_token"] != refresh_token

        refreshed_auth_info = await mock_oauth_provider.load_access_token(new_token_response["access_token"])
        assert refreshed_auth_info
        assert refreshed_auth_info.subject == "test-user"

        response = await test_client.post(
            "/revoke",
            data={
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "token": new_token_response["access_token"],
            },
        )
        assert response.status_code == 200

        assert await mock_oauth_provider.load_access_token(new_token_response["access_token"]) is None

    @pytest.mark.anyio
    async def test_revoke_invalid_token(self, test_client: httpx.AsyncClient, registered_client: dict[str, Any]):
        response = await test_client.post(
            "/revoke",
            data={
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "token": "invalid_token",
            },
        )
        # Per RFC 7009, revocation returns 200 even if the token is invalid.
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_revoke_with_malformed_token(self, test_client: httpx.AsyncClient, registered_client: dict[str, Any]):
        response = await test_client.post(
            "/revoke",
            data={
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "token": 123,
                "token_type_hint": "asdf",
            },
        )
        assert response.status_code == 400
        error_response = response.json()
        assert error_response["error"] == "invalid_request"
        assert "token_type_hint" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_client_registration_disallowed_scopes(self, test_client: httpx.AsyncClient):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "scope": "read write profile admin",  # 'admin' is not in valid_scopes
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert "scope" in error_data["error_description"]
        assert "admin" in error_data["error_description"]

    @pytest.mark.anyio
    async def test_client_registration_default_scopes(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            # No scope specified
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()

        assert client_info["scope"] == "read write"

        registered_client = await mock_oauth_provider.get_client(client_info["client_id"])
        assert registered_client is not None

        assert registered_client.scope == "read write"

    @pytest.mark.anyio
    async def test_client_registration_with_authorization_code_only(self, test_client: httpx.AsyncClient):
        """The refresh_token grant type is optional per RFC 7591."""
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()
        assert "client_id" in client_info
        assert client_info["grant_types"] == ["authorization_code"]

    @pytest.mark.anyio
    async def test_client_registration_missing_authorization_code(self, test_client: httpx.AsyncClient):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert error_data["error_description"] == "grant_types must include 'authorization_code'"

    @pytest.mark.anyio
    async def test_client_registration_with_additional_grant_type(self, test_client: httpx.AsyncClient):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:device_code"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()

        assert "client_id" in client_info
        assert "client_secret" in client_info
        assert client_info["client_name"] == "Test Client"

    @pytest.mark.anyio
    async def test_client_registration_with_additional_response_types(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code", "none"],  # Keycloak-style response with additional value
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        data = response.json()

        client = await mock_oauth_provider.get_client(data["client_id"])
        assert client is not None
        assert "code" in client.response_types

    @pytest.mark.anyio
    async def test_client_registration_response_types_without_code(self, test_client: httpx.AsyncClient):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["token", "none", "nonsense-string"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert error_data["error"] == "invalid_client_metadata"
        assert "response_types must include 'code'" in error_data["error_description"]

    @pytest.mark.anyio
    async def test_client_registration_default_response_types(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Test Client",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        data = response.json()

        assert "response_types" in data
        assert data["response_types"] == ["code"]

    @pytest.mark.anyio
    async def test_client_secret_basic_authentication(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Basic Auth Client",
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()
        assert client_info["token_endpoint_auth_method"] == "client_secret_basic"

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        credentials = f"{client_info['client_id']}:{client_info['client_secret']}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        response = await test_client.post(
            "/token",
            headers={"Authorization": f"Basic {encoded_credentials}"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 200
        token_response = response.json()
        assert "access_token" in token_response

    @pytest.mark.anyio
    async def test_wrong_auth_method_without_valid_credentials_fails(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Post Auth Client",
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()
        assert client_info["token_endpoint_auth_method"] == "client_secret_post"

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        # Client registered client_secret_post but authenticates via Basic, so the secret is missing from the body.
        credentials = f"{client_info['client_id']}:{client_info['client_secret']}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        response = await test_client.post(
            "/token",
            headers={"Authorization": f"Basic {encoded_credentials}"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Client secret is required" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_basic_auth_without_header_fails(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Basic Auth Client",
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()
        assert client_info["token_endpoint_auth_method"] == "client_secret_basic"

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],  # Secret in body (ignored)
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Missing or invalid Basic authentication" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_basic_auth_invalid_base64_fails(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Basic Auth Client",
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        response = await test_client.post(
            "/token",
            headers={"Authorization": "Basic !!!invalid-base64!!!"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Invalid Basic authentication header" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_basic_auth_no_colon_fails(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Basic Auth Client",
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        invalid_creds = base64.b64encode(b"no-colon-here").decode()
        response = await test_client.post(
            "/token",
            headers={"Authorization": f"Basic {invalid_creds}"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Invalid Basic authentication header" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_basic_auth_client_id_mismatch_fails(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Basic Auth Client",
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        wrong_creds = base64.b64encode(f"wrong-client-id:{client_info['client_secret']}".encode()).decode()
        response = await test_client.post(
            "/token",
            headers={"Authorization": f"Basic {wrong_creds}"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],  # Correct client_id in body
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 401
        error_response = response.json()
        assert error_response["error"] == "invalid_client"
        assert "Client ID mismatch" in error_response["error_description"]

    @pytest.mark.anyio
    async def test_none_auth_method_public_client(
        self, test_client: httpx.AsyncClient, mock_oauth_provider: MockOAuthProvider, pkce_challenge: dict[str, str]
    ):
        client_metadata = {
            "redirect_uris": ["https://client.example.com/callback"],
            "client_name": "Public Client",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
        }

        response = await test_client.post("/register", json=client_metadata)
        assert response.status_code == 201
        client_info = response.json()
        assert client_info["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in client_info or client_info.get("client_secret") is None

        auth_code = f"code_{int(time.time())}"
        mock_oauth_provider.auth_codes[auth_code] = AuthorizationCode(
            code=auth_code,
            client_id=client_info["client_id"],
            code_challenge=pkce_challenge["code_challenge"],
            redirect_uri=AnyUrl("https://client.example.com/callback"),
            redirect_uri_provided_explicitly=True,
            scopes=["read", "write"],
            expires_at=time.time() + 600,
        )

        response = await test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_info["client_id"],
                "code": auth_code,
                "code_verifier": pkce_challenge["code_verifier"],
                "redirect_uri": "https://client.example.com/callback",
            },
        )
        assert response.status_code == 200
        token_response = response.json()
        assert "access_token" in token_response


class TestAuthorizeEndpointErrors:
    @pytest.mark.anyio
    async def test_authorize_missing_client_id(self, test_client: httpx.AsyncClient, pkce_challenge: dict[str, str]):
        """Per OAuth 2.0, a missing client_id shows an error page and does not redirect."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                # Missing client_id
                "redirect_uri": "https://client.example.com/callback",
                "state": "test_state",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 400
        assert "client_id" in response.text.lower()

    @pytest.mark.anyio
    async def test_authorize_invalid_client_id(self, test_client: httpx.AsyncClient, pkce_challenge: dict[str, str]):
        """Per OAuth 2.0, an unknown client_id shows an error page and does not redirect."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "invalid_client_id_that_does_not_exist",
                "redirect_uri": "https://client.example.com/callback",
                "state": "test_state",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 400
        assert "client" in response.text.lower()

    @pytest.mark.anyio
    async def test_authorize_missing_redirect_uri(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        """redirect_uri may be omitted when the client has exactly one registered."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                # Missing redirect_uri
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        assert response.status_code == 302, response.content
        redirect_url = response.headers["location"]
        assert redirect_url.startswith("https://client.example.com/callback")

    @pytest.mark.anyio
    async def test_authorize_invalid_redirect_uri(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        """Per OAuth 2.0, a non-matching redirect_uri shows an error page and does not redirect."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://attacker.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        assert response.status_code == 400, response.content
        assert "redirect" in response.text.lower()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "registered_client",
        [
            {
                "redirect_uris": [
                    "https://client.example.com/callback",
                    "https://client.example.com/other-callback",
                ]
            }
        ],
        indirect=True,
    )
    async def test_authorize_missing_redirect_uri_multiple_registered(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        """redirect_uri is required when the client has multiple registered."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                # Missing redirect_uri
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        assert response.status_code == 400
        assert "redirect_uri" in response.text.lower()

    @pytest.mark.anyio
    async def test_authorize_unsupported_response_type(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        """Per OAuth 2.0, unsupported_response_type errors redirect back with error parameters."""
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "token",  # Only "code" is supported
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        assert response.status_code == 302
        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "error" in query_params
        assert query_params["error"][0] == "unsupported_response_type"
        assert "state" in query_params
        assert query_params["state"][0] == "test_state"

    @pytest.mark.anyio
    async def test_authorize_missing_response_type(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        response = await test_client.get(
            "/authorize",
            params={
                # Missing response_type
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "state": "test_state",
            },
        )

        assert response.status_code == 302
        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "error" in query_params
        assert query_params["error"][0] == "invalid_request"
        assert "state" in query_params
        assert query_params["state"][0] == "test_state"

    @pytest.mark.anyio
    async def test_authorize_missing_pkce_challenge(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any]
    ):
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                # Missing code_challenge
                "state": "test_state",
            },
        )

        assert response.status_code == 302
        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "error" in query_params
        assert query_params["error"][0] == "invalid_request"
        assert "state" in query_params
        assert query_params["state"][0] == "test_state"

    @pytest.mark.anyio
    async def test_authorize_invalid_scope(
        self, test_client: httpx.AsyncClient, registered_client: dict[str, Any], pkce_challenge: dict[str, str]
    ):
        response = await test_client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example.com/callback",
                "code_challenge": pkce_challenge["code_challenge"],
                "code_challenge_method": "S256",
                "scope": "invalid_scope_that_does_not_exist",
                "state": "test_state",
            },
        )

        assert response.status_code == 302
        redirect_url = response.headers["location"]
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)

        assert "error" in query_params
        assert query_params["error"][0] == "invalid_scope"
        assert "state" in query_params
        assert query_params["state"][0] == "test_state"
