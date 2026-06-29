"""Resource-server bearer-token gate: status codes and `WWW-Authenticate` for each token shape.

Mounts only the resource-server side (a `StaticTokenVerifier`, no authorization-server provider)
and speaks raw HTTP: every assertion is about HTTP semantics the SDK `Client` cannot observe.
The flow side of the same 401 is `test_flow.py`'s flagship test.
"""

import time
from collections.abc import AsyncIterator

import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import JSONRPCResponse

from mcp.server import Server
from mcp.server.auth.provider import AccessToken
from tests.interaction._connect import base_headers, initialize_body, mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import StaticTokenVerifier, auth_settings

pytestmark = pytest.mark.anyio

REQUIRED_SCOPE = "mcp:read"
RESOURCE_METADATA_URL = "http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

_FUTURE = int(time.time()) + 3600
_PAST = int(time.time()) - 3600

TOKENS = {
    "tok-valid": AccessToken(token="tok-valid", client_id="c", scopes=[REQUIRED_SCOPE], expires_at=_FUTURE),
    "tok-expired": AccessToken(token="tok-expired", client_id="c", scopes=[REQUIRED_SCOPE], expires_at=_PAST),
    "tok-noscope": AccessToken(token="tok-noscope", client_id="c", scopes=["other:thing"], expires_at=_FUTURE),
    "tok-wrong-aud": AccessToken(
        token="tok-wrong-aud",
        client_id="c",
        scopes=[REQUIRED_SCOPE],
        expires_at=_FUTURE,
        resource="https://other.example/mcp",
    ),
}


@pytest.fixture
async def protected() -> AsyncIterator[httpx.AsyncClient]:
    """A bearer-gated streamable-HTTP app (resource server only) on the in-process bridge."""
    server = Server("rs")
    settings = auth_settings(required_scopes=[REQUIRED_SCOPE])
    async with mounted_app(server, auth=settings, token_verifier=StaticTokenVerifier(TOKENS)) as (http, _):
        yield http


async def post_mcp(
    http: httpx.AsyncClient, *, bearer: str | None = None, query: dict[str, str] | None = None
) -> httpx.Response:
    headers = base_headers()
    if bearer is not None:
        headers["authorization"] = f"Bearer {bearer}"
    return await http.post("/mcp", headers=headers, params=query, json=initialize_body())


def parse_www_authenticate(value: str) -> dict[str, str]:
    """Parse a `Bearer k="v", k="v"` challenge into a dict.

    Assumes the SDK's exact format (each parameter once, comma-space separated, quote-free
    double-quoted values) and fails visibly if it changes.
    """
    scheme, _, params = value.partition(" ")
    assert scheme == "Bearer"
    return {key: quoted.strip('"') for key, _, quoted in (pair.partition("=") for pair in params.split(", "))}


@requirement("hosting:auth:missing-401")
async def test_a_request_with_no_authorization_header_is_challenged_with_resource_metadata(
    protected: httpx.AsyncClient,
) -> None:
    """The SDK collapses no-header, unknown-token, and expired-token into one `invalid_token`
    challenge. Recorded divergences: no `scope` (spec SHOULD include it) and an error code on a
    no-credentials request (RFC 6750 SHOULD NOT). The exact-dict assertion also pins that no
    parameter appears twice."""
    response = await post_mcp(protected)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == snapshot(
        'Bearer error="invalid_token", error_description="Authentication required", '
        'resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"'
    )
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "Authentication required",
        "resource_metadata": RESOURCE_METADATA_URL,
    }
    assert response.json() == snapshot({"error": "invalid_token", "error_description": "Authentication required"})


@requirement("hosting:auth:invalid-401")
async def test_an_unrecognized_bearer_token_is_answered_401_invalid_token(protected: httpx.AsyncClient) -> None:
    """Identical challenge to the no-header case (the backend returns `None` for both); the
    missing `scope` parameter is the recorded divergence."""
    response = await post_mcp(protected, bearer="tok-unknown")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "Authentication required",
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:expired-401")
async def test_an_expired_token_is_answered_401(protected: httpx.AsyncClient) -> None:
    """The bearer backend checks expiry against the wall clock, so a concrete past timestamp
    suffices (no time mocking); the missing `scope` parameter is the recorded divergence."""
    response = await post_mcp(protected, bearer="tok-expired")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"])["error"] == "invalid_token"


@requirement("hosting:auth:scope-403")
async def test_a_token_missing_a_required_scope_is_answered_403_insufficient_scope_without_a_scope_param(
    protected: httpx.AsyncClient,
) -> None:
    """The spec says this challenge SHOULD include `scope` naming the required scope; the SDK
    never emits it (the recorded divergence). The SDK client reads `scope` from this header to
    drive step-up, so the gap is a resource-server/client asymmetry."""
    response = await post_mcp(protected, bearer="tok-noscope")

    assert response.status_code == 403
    parsed = parse_www_authenticate(response.headers["www-authenticate"])
    assert parsed == {
        "error": "insufficient_scope",
        "error_description": f"Required scope: {REQUIRED_SCOPE}",
        "resource_metadata": RESOURCE_METADATA_URL,
    }
    assert "scope" not in parsed


@requirement("hosting:auth:aud-validation")
async def test_a_token_with_a_mismatched_audience_is_accepted(protected: httpx.AsyncClient) -> None:
    """The bearer backend never inspects `AccessToken.resource`, so a wrong-audience token passes
    the gate despite the spec mandating audience validation; the recorded divergence."""
    response = await post_mcp(protected, bearer="tok-wrong-aud")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # Pull the JSON-RPC response out of the buffered SSE text to prove the MCP endpoint answered.
    [data] = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert "protocolVersion" in JSONRPCResponse.model_validate_json(data).result


@requirement("hosting:auth:query-token-ignored")
async def test_an_access_token_in_the_query_string_is_not_accepted(protected: httpx.AsyncClient) -> None:
    """The bearer backend reads only the `Authorization` header, so `?access_token=...` is never
    consulted — satisfying, by absence, the best practice that resource servers must not accept
    query-string tokens."""
    response = await post_mcp(protected, query={"access_token": "tok-valid"})

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"])["error"] == "invalid_token"
