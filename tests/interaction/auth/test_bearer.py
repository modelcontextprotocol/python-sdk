"""Resource-server bearer-token gate: status codes and `WWW-Authenticate` for each token shape.

These tests mount only the resource-server side of the auth wiring (a `StaticTokenVerifier`
seeded with hand-built tokens, no authorization-server provider) and speak raw HTTP, since
every assertion is about HTTP semantics the SDK `Client` cannot observe: the 401/403 status,
the `WWW-Authenticate` header structure, and that the audience gate fails closed (a token with
no audience claim is rejected unless `AuthSettings.verifier_validates_audience` opts the gate
out). The flow side of the same 401 is `test_flow.py`'s flagship test.
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
# The audience `auth_settings()` configures as `resource_server_url`. Every fixture token with
# exactly one non-audience defect carries it, so each token isolates the defect its test names.
RESOURCE = "http://127.0.0.1:8000/mcp"

TOKENS = {
    "tok-valid": AccessToken(
        token="tok-valid", client_id="c", scopes=[REQUIRED_SCOPE], expires_at=_FUTURE, resource=RESOURCE
    ),
    "tok-expired": AccessToken(
        token="tok-expired", client_id="c", scopes=[REQUIRED_SCOPE], expires_at=_PAST, resource=RESOURCE
    ),
    "tok-noscope": AccessToken(
        token="tok-noscope", client_id="c", scopes=["other:thing"], expires_at=_FUTURE, resource=RESOURCE
    ),
    "tok-wrong-aud": AccessToken(
        token="tok-wrong-aud",
        client_id="c",
        scopes=[REQUIRED_SCOPE],
        expires_at=_FUTURE,
        resource="https://other.example/mcp",
    ),
    "tok-parent-aud": AccessToken(
        token="tok-parent-aud",
        client_id="c",
        scopes=[REQUIRED_SCOPE],
        expires_at=_FUTURE,
        resource="http://127.0.0.1:8000/",
    ),
    "tok-no-aud": AccessToken(token="tok-no-aud", client_id="c", scopes=[REQUIRED_SCOPE], expires_at=_FUTURE),
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

    RFC 6750 §3: a no-credentials challenge carries no error code. The snapshot pins the
    full header (parameter order included); asserting the dict equals an exact key set also
    pins that no parameter appears twice.
    """
    response = await post_mcp(protected)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == snapshot(
        'Bearer scope="mcp:read", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"'
    )
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }
    assert response.json() == snapshot({})


@requirement("hosting:auth:invalid-401")
async def test_an_unrecognized_bearer_token_is_answered_401_invalid_token(protected: httpx.AsyncClient) -> None:
    """A token the verifier does not recognize is answered 401 `invalid_token`.

    The challenge is distinct from the no-header case: a bearer token was presented, so RFC
    6750 §3.1's `error` and `error_description` apply.
    """
    response = await post_mcp(protected, bearer="tok-unknown")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "The access token is malformed or unknown",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:expired-401")
async def test_an_expired_token_is_answered_401(protected: httpx.AsyncClient) -> None:
    """A token whose `expires_at` is in the past is answered 401 `invalid_token`.

    The expiry check is the bearer backend's, against the wall clock; the test seeds a concrete
    past timestamp so no time mocking is involved.
    """
    response = await post_mcp(protected, bearer="tok-expired")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "The access token has expired",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:scope-403")
async def test_a_token_missing_a_required_scope_is_answered_403_with_the_required_scope_in_the_challenge(
    protected: httpx.AsyncClient,
) -> None:
    """A token lacking the required scope is answered 403 `insufficient_scope` with `scope=` naming what's needed.

    The SDK client reads `scope` from this header to drive step-up, so the parameter is the
    contract between resource server and client.
    """
    response = await post_mcp(protected, bearer="tok-noscope")

    assert response.status_code == 403
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "insufficient_scope",
        "error_description": "The access token lacks a required scope",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:aud-validation")
async def test_a_token_with_a_mismatched_audience_is_answered_401_invalid_token(protected: httpx.AsyncClient) -> None:
    """A token whose `resource` does not match the server's resource identifier is answered 401.

    Spec-mandated: the resource server MUST validate the token's audience and reject tokens
    not issued specifically for it.
    """
    response = await post_mcp(protected, bearer="tok-wrong-aud")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "The access token was issued for a different resource",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:aud-validation")
async def test_a_token_for_a_parent_path_on_the_same_origin_is_answered_401_invalid_token(
    protected: httpx.AsyncClient,
) -> None:
    """A token whose audience is the same origin but a parent path is answered 401.

    This is the discriminating case for canonical-URI equality: under hierarchical prefix
    semantics a token for `http://host/` would be accepted by a server at `http://host/mcp`;
    under audience binding it must be rejected. The cross-origin case above cannot catch a
    regression to prefix semantics.
    """
    response = await post_mcp(protected, bearer="tok-parent-aud")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "The access token was issued for a different resource",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:aud-validation")
async def test_a_token_without_a_resource_claim_is_answered_401_invalid_token(
    protected: httpx.AsyncClient,
) -> None:
    """A token whose `AccessToken.resource` is unset is answered 401 when an audience is configured.

    Spec-mandated (authorization MUST: servers reject tokens that do not include them in the
    audience claim). The bearer gate fails closed; the operator-level escape hatch for
    verifiers that validate audience internally is `AuthSettings.verifier_validates_audience`.
    """
    response = await post_mcp(protected, bearer="tok-no-aud")

    assert response.status_code == 401
    assert parse_www_authenticate(response.headers["www-authenticate"]) == {
        "error": "invalid_token",
        "error_description": "The access token carries no audience claim",
        "scope": REQUIRED_SCOPE,
        "resource_metadata": RESOURCE_METADATA_URL,
    }


@requirement("hosting:auth:aud-validation")
async def test_a_token_without_a_resource_claim_passes_when_verifier_validates_audience_is_set() -> None:
    """With `verifier_validates_audience=True` the bearer gate skips its own audience check.

    SDK-defined opt-out for the spec's "or otherwise verify" clause: a verifier that validates
    the token's audience internally (a JWT decoder configured with the expected audience) and so
    never populates `AccessToken.resource`. The body proves the request reached the MCP endpoint.
    """
    server = Server("rs")
    settings = auth_settings(required_scopes=[REQUIRED_SCOPE]).model_copy(update={"verifier_validates_audience": True})
    async with mounted_app(server, auth=settings, token_verifier=StaticTokenVerifier(TOKENS)) as (http, _):
        response = await post_mcp(http, bearer="tok-no-aud")

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
    parsed = parse_www_authenticate(response.headers["www-authenticate"])
    assert "error" not in parsed
    assert parsed["scope"] == REQUIRED_SCOPE
