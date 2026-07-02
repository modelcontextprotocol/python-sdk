"""Resource-server bearer-token gate: status codes and `WWW-Authenticate` for each token shape.

These tests mount only the resource-server side of the auth wiring (a `StaticTokenVerifier`
seeded with hand-built tokens, no authorization-server provider) and speak raw HTTP, since
every assertion is about HTTP semantics the SDK `Client` cannot observe: the 401/403 status,
the `WWW-Authenticate` header structure, and that a wrong-audience token reaches the MCP
endpoint behind the gate. The flow side of the same 401 is `test_flow.py`'s flagship test.
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
    """POST an initialize body to `/mcp`, optionally with a bearer token and/or a query string."""
    headers = base_headers()
    if bearer is not None:
        headers["authorization"] = f"Bearer {bearer}"
    return await http.post("/mcp", headers=headers, params=query, json=initialize_body())


def parse_www_authenticate(value: str) -> dict[str, str]:
    """Parse a `Bearer k="v", k="v"` challenge into a dict.

    The SDK emits each parameter exactly once, comma-space separated, with double-quoted
    values that contain no quotes themselves; this helper relies on that and would fail
    visibly if the format changed.
    """
    scheme, _, params = value.partition(" ")
    assert scheme == "Bearer"
    return {key: quoted.strip('"') for key, _, quoted in (pair.partition("=") for pair in params.split(", "))}


@requirement("hosting:auth:missing-401")
async def test_a_request_with_no_authorization_header_is_challenged_with_resource_metadata(
    protected: httpx.AsyncClient,
) -> None:
    """No `Authorization` header → 401 with a `WWW-Authenticate` carrying `resource_metadata`.

    The snapshot pins current behaviour: the SDK collapses the no-header, unknown-token, and
    expired-token cases into one challenge (`error="invalid_token"`, no `scope` parameter). The
    spec says the discovery-time challenge SHOULD include `scope` and RFC 6750 says the
    no-credentials case SHOULD NOT carry an error code; both gaps are recorded as the divergence
    on this requirement. Asserting the dict equals an exact key set also pins that no parameter
    appears twice.
    """
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
    """A token the verifier does not recognize is answered 401 `invalid_token`.

    The challenge is identical to the no-header case (the backend returns `None` for both); the
    missing `scope` parameter is the recorded divergence on this requirement.
    """
    response = await post_mcp(protected, bearer="tok-unknown")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "Authentication required",
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:expired-401")
async def test_an_expired_token_is_answered_401(protected: httpx.AsyncClient) -> None:
    """A token whose `expires_at` is in the past is answered 401 `invalid_token`.

    The expiry check is the bearer backend's, against the wall clock; the test seeds a concrete
    past timestamp so no time mocking is involved. The missing `scope` parameter is the recorded
    divergence on this requirement.
    """
    response = await post_mcp(protected, bearer="tok-expired")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"])["error"] == "invalid_token"


@requirement("hosting:auth:scope-403")
async def test_a_token_missing_a_required_scope_is_answered_403_insufficient_scope_without_a_scope_param(
    protected: httpx.AsyncClient,
) -> None:
    """A token lacking the required scope is answered 403 `insufficient_scope`, with no `scope` parameter.

    The spec's runtime-insufficient-scope guidance says the challenge SHOULD include `scope`
    naming the required scope; the SDK never emits it, recorded as the divergence on this
    requirement. The SDK client reads `scope` from this header to drive step-up, so the gap is
    a resource-server/client asymmetry.
    """
    response = await post_mcp(protected, bearer="tok-noscope")

    assert response.status_code == 403
    parsed = parse_www_authenticate(response.headers["www-authenticate"])
    assert parsed == {
        "error": "insufficient_scope",
        "error_description": f"Required scope: {REQUIRED_SCOPE}",
        "resource_metadata": RESOURCE_METADATA_URL,
    }
    assert "scope" not in parsed


@requirement("hosting:auth:scope-403:all-scopes")
async def test_a_token_missing_two_required_scopes_is_challenged_with_only_the_first() -> None:
    """A token missing both required scopes is challenged for only the first missing scope.

    Pins the recorded divergence: the middleware checks required scopes in order and names
    only the first missing one, where the spec wants all of them in a single challenge.
    When the middleware aggregates: re-pin to a challenge naming both scopes and delete the Divergence.
    """
    settings = auth_settings(required_scopes=["mcp:read", "mcp:write"])
    verifier = StaticTokenVerifier(
        {"tok-zeroscope": AccessToken(token="tok-zeroscope", client_id="c", scopes=["other:thing"], expires_at=_FUTURE)}
    )

    async with mounted_app(Server("rs"), auth=settings, token_verifier=verifier) as (http, _):
        response = await post_mcp(http, bearer="tok-zeroscope")

    assert response.status_code == 403
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "insufficient_scope",
        "error_description": "Required scope: mcp:read",
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:aud-validation")
async def test_a_token_with_a_mismatched_audience_is_accepted(protected: httpx.AsyncClient) -> None:
    """A token whose `resource` does not match the server's resource identifier is accepted.

    The spec mandates the resource server validate the token's audience; the bearer backend
    never inspects `AccessToken.resource`, so the request passes the gate and the MCP endpoint
    serves it. This pins current behaviour with the divergence recorded on the requirement.
    """
    response = await post_mcp(protected, bearer="tok-wrong-aud")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # The body is finite SSE: a result event followed by stream close. Pull the JSON-RPC response
    # out of the buffered text to prove the MCP endpoint actually answered the initialize request.
    [data] = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert "protocolVersion" in JSONRPCResponse.model_validate_json(data).result


@requirement("hosting:auth:query-token-ignored")
async def test_an_access_token_in_the_query_string_is_not_accepted(protected: httpx.AsyncClient) -> None:
    """A valid token presented in the URI query string is treated as no authentication.

    The bearer backend reads only the `Authorization` header, so `?access_token=...` is never
    consulted; the request is treated as unauthenticated and answered 401. This satisfies, by
    absence, the security best-practice that resource servers must not accept query-string
    tokens.
    """
    response = await post_mcp(protected, query={"access_token": "tok-valid"})

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"])["error"] == "invalid_token"
