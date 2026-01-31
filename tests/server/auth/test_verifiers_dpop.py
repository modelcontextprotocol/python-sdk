"""Unit tests for DPoP integration with OAuthTokenVerifier."""

import pytest
from starlette.requests import Request

from mcp.client.auth.dpop import DPoPKeyPair, DPoPProofGeneratorImpl
from mcp.server.auth.dpop import DPoPProofVerifier, InMemoryJTIReplayStore
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.verifiers import OAuthTokenVerifier


class MockTokenVerifier:
    """Mock TokenVerifier for testing."""

    def __init__(self, valid_tokens: dict[str, AccessToken]) -> None:
        self._valid_tokens = valid_tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._valid_tokens.get(token)


def _make_request(
    method: str,
    url: str,
    headers: dict[str, str],
) -> Request:
    """Create a Starlette Request for testing."""
    # Extract path from URL (e.g., "https://example.com/api/resource" -> "/api/resource")
    if "://" in url:
        path_part = url.split("://")[-1].split("/", 1)
        path = "/" + path_part[1] if len(path_part) > 1 else "/"
    else:
        path = url
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "server": ("example.com", 443),
        "scheme": "https",
    }
    return Request(scope)


@pytest.fixture
def valid_token() -> AccessToken:
    return AccessToken(
        token="valid-access-token",
        client_id="test-client",
        scopes=["read", "write"],
    )


@pytest.fixture
def token_verifier(valid_token: AccessToken) -> MockTokenVerifier:
    return MockTokenVerifier({"valid-access-token": valid_token})


@pytest.fixture
def oauth_verifier(token_verifier: MockTokenVerifier) -> OAuthTokenVerifier:
    return OAuthTokenVerifier(token_verifier)


@pytest.fixture
def dpop_verifier() -> DPoPProofVerifier:
    return DPoPProofVerifier(jti_store=InMemoryJTIReplayStore())


@pytest.fixture
def key_pair() -> DPoPKeyPair:
    return DPoPKeyPair.generate("ES256")


@pytest.fixture
def dpop_generator(key_pair: DPoPKeyPair) -> DPoPProofGeneratorImpl:
    return DPoPProofGeneratorImpl(key_pair)


@pytest.mark.anyio
async def test_bearer_token_without_dpop(oauth_verifier: OAuthTokenVerifier) -> None:
    """Bearer token should work without DPoP verification."""
    request = _make_request(
        "GET",
        "https://example.com/api/resource",
        {"Authorization": "Bearer valid-access-token"},
    )
    result = await oauth_verifier.verify(request)
    assert result is not None
    assert result.token == "valid-access-token"


@pytest.mark.anyio
async def test_bearer_token_with_dpop_verifier_no_proof(
    oauth_verifier: OAuthTokenVerifier,
    dpop_verifier: DPoPProofVerifier,
) -> None:
    """Bearer token without DPoP proof should still work when dpop_verifier provided."""
    request = _make_request(
        "GET",
        "https://example.com/api/resource",
        {"Authorization": "Bearer valid-access-token"},
    )
    result = await oauth_verifier.verify(request, dpop_verifier=dpop_verifier)
    assert result is not None
    assert result.token == "valid-access-token"


@pytest.mark.anyio
async def test_bearer_token_with_valid_dpop_proof(
    oauth_verifier: OAuthTokenVerifier,
    dpop_verifier: DPoPProofVerifier,
    dpop_generator: DPoPProofGeneratorImpl,
) -> None:
    """Bearer token with valid DPoP proof should pass verification."""
    proof = dpop_generator.generate_proof(
        "GET",
        "https://example.com/api/resource",
        credential="valid-access-token",
    )
    request = _make_request(
        "GET",
        "https://example.com/api/resource",
        {
            "Authorization": "Bearer valid-access-token",
            "DPoP": proof,
        },
    )
    result = await oauth_verifier.verify(request, dpop_verifier=dpop_verifier)
    assert result is not None
    assert result.token == "valid-access-token"


@pytest.mark.anyio
async def test_dpop_bound_token_requires_proof(
    oauth_verifier: OAuthTokenVerifier,
    dpop_verifier: DPoPProofVerifier,
) -> None:
    """DPoP-bound token (Authorization: DPoP) without proof should fail."""
    request = _make_request(
        "GET",
        "https://example.com/api/resource",
        {"Authorization": "DPoP valid-access-token"},
    )
    result = await oauth_verifier.verify(request, dpop_verifier=dpop_verifier)
    assert result is None


@pytest.mark.anyio
async def test_dpop_bound_token_with_valid_proof(
    oauth_verifier: OAuthTokenVerifier,
    dpop_verifier: DPoPProofVerifier,
    dpop_generator: DPoPProofGeneratorImpl,
) -> None:
    """DPoP-bound token with valid proof should pass."""
    proof = dpop_generator.generate_proof(
        "GET",
        "https://example.com/api/resource",
        credential="valid-access-token",
    )
    request = _make_request(
        "GET",
        "https://example.com/api/resource",
        {
            "Authorization": "DPoP valid-access-token",
            "DPoP": proof,
        },
    )
    result = await oauth_verifier.verify(request, dpop_verifier=dpop_verifier)
    assert result is not None


@pytest.mark.anyio
async def test_dpop_proof_method_mismatch_fails(
    oauth_verifier: OAuthTokenVerifier,
    dpop_verifier: DPoPProofVerifier,
    dpop_generator: DPoPProofGeneratorImpl,
) -> None:
    """DPoP proof with mismatched HTTP method should fail."""
    proof = dpop_generator.generate_proof(
        "POST",  # Wrong method
        "https://example.com/api/resource",
        credential="valid-access-token",
    )
    request = _make_request(
        "GET",  # Actual request method
        "https://example.com/api/resource",
        {
            "Authorization": "Bearer valid-access-token",
            "DPoP": proof,
        },
    )
    result = await oauth_verifier.verify(request, dpop_verifier=dpop_verifier)
    assert result is None
