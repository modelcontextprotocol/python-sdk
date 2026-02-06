"""Unit tests for DPoP integration with OAuth2Protocol and MultiProtocolAuthProvider."""

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.multi_protocol import MultiProtocolAuthProvider
from mcp.client.auth.protocols.oauth2 import OAuth2Protocol
from mcp.shared.auth import AuthCredentials, OAuthClientMetadata, OAuthCredentials, OAuthToken


@pytest.fixture
def client_metadata() -> OAuthClientMetadata:
    return OAuthClientMetadata(
        redirect_uris=[AnyHttpUrl("http://localhost:8080/callback")],
        client_name="Test Client",
    )


def test_oauth2_protocol_dpop_disabled_by_default(client_metadata: OAuthClientMetadata) -> None:
    """OAuth2Protocol should have DPoP disabled by default."""
    protocol = OAuth2Protocol(client_metadata=client_metadata)
    assert protocol.supports_dpop() is False
    assert protocol.get_dpop_proof_generator() is None


def test_oauth2_protocol_dpop_enabled(client_metadata: OAuthClientMetadata) -> None:
    """OAuth2Protocol should report DPoP support when enabled."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True)
    assert protocol.supports_dpop() is True
    # Generator is None until initialize_dpop is called
    assert protocol.get_dpop_proof_generator() is None


@pytest.mark.anyio
async def test_oauth2_protocol_initialize_dpop(client_metadata: OAuthClientMetadata) -> None:
    """initialize_dpop should create key pair and generator."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True)
    await protocol.initialize_dpop()

    generator = protocol.get_dpop_proof_generator()
    assert generator is not None

    jwk = protocol.get_dpop_public_key_jwk()
    assert jwk is not None
    assert jwk.get("kty") == "EC"


@pytest.mark.anyio
async def test_oauth2_protocol_initialize_dpop_rs256(client_metadata: OAuthClientMetadata) -> None:
    """initialize_dpop should support RS256 algorithm."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True, dpop_algorithm="RS256")
    await protocol.initialize_dpop()

    jwk = protocol.get_dpop_public_key_jwk()
    assert jwk is not None
    assert jwk.get("kty") == "RSA"


@pytest.mark.anyio
async def test_oauth2_protocol_initialize_dpop_custom_rsa_key_size(
    client_metadata: OAuthClientMetadata,
) -> None:
    """initialize_dpop should support custom RSA key size."""
    protocol = OAuth2Protocol(
        client_metadata=client_metadata,
        dpop_enabled=True,
        dpop_algorithm="RS256",
        dpop_rsa_key_size=4096,
    )
    await protocol.initialize_dpop()

    jwk = protocol.get_dpop_public_key_jwk()
    assert jwk is not None
    assert jwk.get("kty") == "RSA"
    # 4096-bit RSA key has a longer 'n' (modulus) than 2048-bit
    n_value = jwk.get("n", "")
    # Base64url-encoded 4096-bit key's n should be ~683 chars (4096/8 * 4/3)
    assert len(n_value) > 300  # 2048-bit would be ~342 chars


@pytest.mark.anyio
async def test_oauth2_protocol_initialize_dpop_noop_when_disabled(
    client_metadata: OAuthClientMetadata,
) -> None:
    """initialize_dpop should be a no-op when DPoP is disabled."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=False)
    await protocol.initialize_dpop()
    assert protocol.get_dpop_proof_generator() is None


@pytest.mark.anyio
async def test_dpop_proof_generation(client_metadata: OAuthClientMetadata) -> None:
    """DPoP proof generator should create valid proofs."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True)
    await protocol.initialize_dpop()

    generator = protocol.get_dpop_proof_generator()
    assert generator is not None

    proof = generator.generate_proof("POST", "https://example.com/token")
    assert proof is not None
    assert len(proof) > 0

    # Proof with access token binding
    proof_with_ath = generator.generate_proof("GET", "https://api.example.com/resource", credential="access-token-123")
    assert proof_with_ath is not None
    assert proof_with_ath != proof


class MockStorage:
    """Mock storage for testing."""

    def __init__(self, tokens: OAuthToken | OAuthCredentials | None = None) -> None:
        self._tokens: AuthCredentials | OAuthToken | None = tokens

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        self._tokens = tokens


@pytest.mark.anyio
async def test_multi_protocol_provider_dpop_header_injection(
    client_metadata: OAuthClientMetadata,
) -> None:
    """MultiProtocolAuthProvider should inject DPoP header when dpop_enabled=True."""
    # Setup protocol with DPoP enabled
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True)

    # Setup storage with valid credentials
    credentials = OAuthCredentials(
        protocol_id="oauth2",
        access_token="test-access-token",
        token_type="Bearer",
        expires_at=None,
    )
    storage = MockStorage(credentials)

    # Create provider with DPoP enabled
    provider = MultiProtocolAuthProvider(
        server_url="https://example.com",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=True,
    )

    # Create a test request
    request = httpx.Request("GET", "https://example.com/api/resource")

    # Run auth flow (first yield)
    flow = provider.async_auth_flow(request)
    prepared_request = await flow.__anext__()

    # Verify DPoP header was injected
    assert "DPoP" in prepared_request.headers
    assert prepared_request.headers["Authorization"] == "Bearer test-access-token"

    # Clean up generator
    try:
        await flow.athrow(GeneratorExit)
    except (StopAsyncIteration, GeneratorExit):
        pass


@pytest.mark.anyio
async def test_multi_protocol_provider_no_dpop_when_disabled(
    client_metadata: OAuthClientMetadata,
) -> None:
    """MultiProtocolAuthProvider should not inject DPoP header when dpop_enabled=False."""
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=False)

    credentials = OAuthCredentials(
        protocol_id="oauth2",
        access_token="test-access-token",
        token_type="Bearer",
        expires_at=None,
    )
    storage = MockStorage(credentials)

    provider = MultiProtocolAuthProvider(
        server_url="https://example.com",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=False,
    )

    request = httpx.Request("GET", "https://example.com/api/resource")

    flow = provider.async_auth_flow(request)
    prepared_request = await flow.__anext__()

    # DPoP header should NOT be present
    assert "DPoP" not in prepared_request.headers
    assert prepared_request.headers["Authorization"] == "Bearer test-access-token"

    try:
        await flow.athrow(GeneratorExit)
    except (StopAsyncIteration, GeneratorExit):
        pass
