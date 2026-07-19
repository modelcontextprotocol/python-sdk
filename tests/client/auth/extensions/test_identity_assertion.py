"""Unit tests for the standalone SEP-990 jwt-bearer `httpx2.Auth`.

The provider's authorization server is configuration; these tests assert that authorization-server
metadata is fetched only from the configured issuer, that the resource server is never consulted for
AS selection, and that the ID-JAG and client secret reach only the issuer's token endpoint.
"""

import base64
import json
import urllib.parse

import httpx2
import pytest

from mcp.client.auth import OAuthFlowError, OAuthTokenError
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider, _origin
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthToken

ISSUER = "https://auth.example.com"
RS = "https://mcp.example.com"
ASM_PATH = "/.well-known/oauth-authorization-server"
OIDC_PATH = "/.well-known/openid-configuration"


class InMemoryStorage:
    def __init__(self, tokens: OAuthToken | None = None) -> None:
        self.tokens = tokens

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raise NotImplementedError

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError


def asm_body(*, issuer: str = ISSUER, token_endpoint: str | None = None) -> bytes:
    return json.dumps(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": token_endpoint or f"{issuer}/token",
        }
    ).encode()


def token_body(*, access_token: str = "issued-token", scope: str | None = None) -> bytes:
    payload: dict[str, object] = {"access_token": access_token, "token_type": "Bearer", "expires_in": 3600}
    if scope is not None:
        payload["scope"] = scope
    return json.dumps(payload).encode()


def make_provider(
    storage: InMemoryStorage | None = None,
    *,
    scope: str | None = "mcp",
    token_endpoint_auth_method: str = "client_secret_post",
    record: list[tuple[str, str]] | None = None,
) -> IdentityAssertionOAuthProvider:
    async def assertion_provider(audience: str, resource: str) -> str:
        if record is not None:
            record.append((audience, resource))
        return "the-id-jag"

    return IdentityAssertionOAuthProvider(
        server_url=f"{RS}/mcp",
        storage=storage if storage is not None else InMemoryStorage(),
        client_id="test-client-id",
        client_secret="test-client-secret",
        issuer=ISSUER,
        assertion_provider=assertion_provider,
        scope=scope,
        token_endpoint_auth_method=token_endpoint_auth_method,  # type: ignore[arg-type]
    )


def mock_transport(
    requests: list[httpx2.Request],
    *,
    asm: bytes | int = 200,
    token: bytes | int = 200,
    rs_first_status: int = 401,
    rs_first_headers: dict[str, str] | None = None,
) -> httpx2.MockTransport:
    """Build a `MockTransport` that records every request and serves the configured ASM and token.

    `asm` / `token` are either a body (served as 200 JSON) or an int status (served with no body).
    The MCP resource server's first response is `rs_first_status` (default 401) with optional
    headers; subsequent RS requests return 200.
    """
    rs_hits = 0

    def handle(request: httpx2.Request) -> httpx2.Response:
        nonlocal rs_hits
        requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "mcp.example.com":
            rs_hits += 1
            if rs_hits == 1:
                return httpx2.Response(rs_first_status, headers=rs_first_headers or {})
            return httpx2.Response(200, json={"ok": True})
        if host == "auth.example.com" and path in (ASM_PATH, OIDC_PATH):
            if isinstance(asm, int):
                return httpx2.Response(asm)
            return httpx2.Response(200, content=asm, headers={"content-type": "application/json"})
        if host == "auth.example.com" and path == "/token":
            if isinstance(token, int):
                return httpx2.Response(token, json={"error": "invalid_grant"})
            return httpx2.Response(200, content=token, headers={"content-type": "application/json"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")  # pragma: no cover

    return httpx2.MockTransport(handle)


def form(request: httpx2.Request) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(request.content.decode()))


@pytest.mark.anyio
async def test_on_401_exchanges_assertion_at_configured_issuer_and_retries() -> None:
    """A 401 fetches ASM from the configured issuer, posts the jwt-bearer grant, and retries."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    storage = InMemoryStorage()
    auth = make_provider(storage, record=record)

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(), token=token_body(scope="mcp")), auth=auth
    ) as http:
        response = await http.post(f"{RS}/mcp")

    assert [(r.method, str(r.url)) for r in requests] == [
        ("POST", f"{RS}/mcp"),
        ("GET", f"{ISSUER}{ASM_PATH}"),
        ("POST", f"{ISSUER}/token"),
        ("POST", f"{RS}/mcp"),
    ]
    body = form(requests[2])
    assert body == {
        "grant_type": JWT_BEARER_GRANT_TYPE,
        "assertion": "the-id-jag",
        "client_id": "test-client-id",
        "resource": f"{RS}/mcp",
        "scope": "mcp",
        "client_secret": "test-client-secret",
    }
    assert "Authorization" not in requests[2].headers
    assert record == [(ISSUER, f"{RS}/mcp")]
    assert response.status_code == 200
    assert storage.tokens is not None
    assert storage.tokens.access_token == "issued-token"
    assert storage.tokens.scope == "mcp"


@pytest.mark.anyio
async def test_resource_server_metadata_is_never_consulted() -> None:
    """No PRM well-known and no RS-origin ASM well-known is ever fetched.

    This is the by-construction property: the AS is configuration, so the resource server has no
    input into where the ID-JAG or client secret go. Any GET to the RS host fails the test.
    """
    requests: list[httpx2.Request] = []
    auth = make_provider()

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(), token=token_body()), auth=auth
    ) as http:
        await http.post(f"{RS}/mcp")

    rs_gets = [r for r in requests if r.url.host == "mcp.example.com" and r.method == "GET"]
    assert rs_gets == []
    assert all(r.url.host == "auth.example.com" for r in requests if r.method == "GET")
    # No DCR was attempted anywhere.
    assert not any(r.url.path == "/register" for r in requests)


@pytest.mark.anyio
async def test_asm_404_at_configured_issuer_raises_before_minting_assertion() -> None:
    """If the issuer's well-knowns 404, the flow fails closed and the assertion is never minted."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    auth = make_provider(record=record)

    async with httpx2.AsyncClient(transport=mock_transport(requests, asm=404), auth=auth) as http:
        with pytest.raises(OAuthFlowError, match="No authorization server metadata"):
            await http.post(f"{RS}/mcp")

    # Both RFC 8414 and OIDC well-knowns were tried at the configured issuer; nothing else.
    assert [str(r.url) for r in requests if r.method == "GET"] == [f"{ISSUER}{ASM_PATH}", f"{ISSUER}{OIDC_PATH}"]
    assert record == []
    assert not any(r.url.path == "/token" for r in requests)


@pytest.mark.anyio
async def test_asm_5xx_stops_discovery_and_raises() -> None:
    """A 5xx at the issuer's well-known stops discovery without trying further URLs."""
    requests: list[httpx2.Request] = []
    auth = make_provider()

    async with httpx2.AsyncClient(transport=mock_transport(requests, asm=500), auth=auth) as http:
        with pytest.raises(OAuthFlowError, match="No authorization server metadata"):
            await http.post(f"{RS}/mcp")

    assert [str(r.url) for r in requests if r.method == "GET"] == [f"{ISSUER}{ASM_PATH}"]


@pytest.mark.anyio
async def test_asm_with_wrong_issuer_is_rejected_before_minting_assertion() -> None:
    """RFC 8414 section 3.3: metadata whose `issuer` differs from the configured one is rejected."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    auth = make_provider(record=record)

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(issuer="https://other.example")), auth=auth
    ) as http:
        with pytest.raises(OAuthFlowError, match="issuer mismatch"):
            await http.post(f"{RS}/mcp")

    assert record == []
    assert not any(r.url.path == "/token" for r in requests)


@pytest.mark.anyio
async def test_asm_with_off_origin_token_endpoint_is_rejected_before_minting_assertion() -> None:
    """A `token_endpoint` off the configured issuer's origin is refused before any credential is sent."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    auth = make_provider(record=record)

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(token_endpoint="https://other.example/token")), auth=auth
    ) as http:
        with pytest.raises(OAuthFlowError, match="not on the configured issuer origin"):
            await http.post(f"{RS}/mcp")

    assert record == []
    assert not any(r.url.path == "/token" for r in requests)


@pytest.mark.anyio
async def test_403_insufficient_scope_unions_challenged_scope_with_configured() -> None:
    """A 403 `insufficient_scope` re-exchanges with the union of configured and challenged scopes."""
    requests: list[httpx2.Request] = []
    auth = make_provider(scope="mcp")

    transport = mock_transport(
        requests,
        asm=asm_body(),
        token=token_body(),
        rs_first_status=403,
        rs_first_headers={"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="mcp files:write"'},
    )
    async with httpx2.AsyncClient(transport=transport, auth=auth) as http:
        response = await http.post(f"{RS}/mcp")

    [token_req] = [r for r in requests if r.url.path == "/token"]
    assert form(token_req)["scope"] == "mcp files:write"
    assert response.status_code == 200


@pytest.mark.anyio
async def test_403_without_insufficient_scope_does_not_reauthorize() -> None:
    """A plain 403 (not `insufficient_scope`) is returned to the caller without re-exchanging."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    auth = make_provider(record=record)

    transport = mock_transport(requests, rs_first_status=403, rs_first_headers={"WWW-Authenticate": "Bearer"})
    async with httpx2.AsyncClient(transport=transport, auth=auth) as http:
        response = await http.post(f"{RS}/mcp")

    assert response.status_code == 403
    assert record == []
    assert [str(r.url) for r in requests] == [f"{RS}/mcp"]


@pytest.mark.anyio
async def test_token_endpoint_error_surfaces_as_oauth_token_error() -> None:
    requests: list[httpx2.Request] = []
    auth = make_provider()

    async with httpx2.AsyncClient(transport=mock_transport(requests, asm=asm_body(), token=400), auth=auth) as http:
        with pytest.raises(OAuthTokenError, match=r"Token exchange failed \(400\).*invalid_grant"):
            await http.post(f"{RS}/mcp")


@pytest.mark.anyio
async def test_client_secret_basic_sends_basic_header_not_body_secret() -> None:
    requests: list[httpx2.Request] = []
    auth = make_provider(token_endpoint_auth_method="client_secret_basic")

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(), token=token_body()), auth=auth
    ) as http:
        await http.post(f"{RS}/mcp")

    [token_req] = [r for r in requests if r.url.path == "/token"]
    assert "client_secret" not in form(token_req)
    decoded = base64.b64decode(token_req.headers["Authorization"].removeprefix("Basic ")).decode()
    assert decoded == "test-client-id:test-client-secret"


@pytest.mark.anyio
async def test_stored_token_is_reused_without_reauthorizing() -> None:
    """A valid stored token is sent on the first request; on success no ASM or /token is fetched."""
    requests: list[httpx2.Request] = []
    storage = InMemoryStorage(tokens=OAuthToken(access_token="cached", token_type="Bearer", expires_in=3600))
    auth = make_provider(storage)

    transport = mock_transport(requests, rs_first_status=200)
    async with httpx2.AsyncClient(transport=transport, auth=auth) as http:
        response = await http.post(f"{RS}/mcp")

    assert response.status_code == 200
    assert [str(r.url) for r in requests] == [f"{RS}/mcp"]
    assert requests[0].headers["Authorization"] == "Bearer cached"


@pytest.mark.anyio
async def test_second_401_re_exchanges_without_refetching_asm() -> None:
    """ASM is discovered once; a later 401 mints a fresh assertion against the cached token endpoint."""
    requests: list[httpx2.Request] = []
    record: list[tuple[str, str]] = []
    auth = make_provider(record=record)
    rs_hits = 0

    def handle(request: httpx2.Request) -> httpx2.Response:
        nonlocal rs_hits
        requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "mcp.example.com":
            rs_hits += 1
            # First and third RS hits draw a 401; second and fourth succeed.
            return httpx2.Response(401 if rs_hits in (1, 3) else 200)
        if host == "auth.example.com" and path == ASM_PATH:
            return httpx2.Response(200, content=asm_body(), headers={"content-type": "application/json"})
        assert host == "auth.example.com" and path == "/token"
        return httpx2.Response(200, content=token_body(), headers={"content-type": "application/json"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle), auth=auth) as http:
        await http.post(f"{RS}/mcp")
        await http.post(f"{RS}/mcp")

    asm_gets = [r for r in requests if r.url.path == ASM_PATH]
    token_posts = [r for r in requests if r.url.path == "/token"]
    assert len(asm_gets) == 1
    assert len(token_posts) == 2
    assert len(record) == 2


@pytest.mark.anyio
async def test_no_configured_scope_omits_scope_and_backfills_from_request() -> None:
    """With no configured scope and no scope in the token response, the stored token records None."""
    requests: list[httpx2.Request] = []
    storage = InMemoryStorage()
    auth = make_provider(storage, scope=None)

    async with httpx2.AsyncClient(
        transport=mock_transport(requests, asm=asm_body(), token=token_body()), auth=auth
    ) as http:
        await http.post(f"{RS}/mcp")

    [token_req] = [r for r in requests if r.url.path == "/token"]
    assert "scope" not in form(token_req)
    assert storage.tokens is not None
    assert storage.tokens.scope is None


def test_empty_client_secret_is_rejected() -> None:
    async def assertion_provider(audience: str, resource: str) -> str:
        raise NotImplementedError

    with pytest.raises(ValueError, match="client_secret is required"):
        IdentityAssertionOAuthProvider(
            server_url=f"{RS}/mcp",
            storage=InMemoryStorage(),
            client_id="c",
            client_secret="",
            issuer=ISSUER,
            assertion_provider=assertion_provider,
        )


def test_empty_issuer_is_rejected() -> None:
    async def assertion_provider(audience: str, resource: str) -> str:
        raise NotImplementedError

    with pytest.raises(ValueError, match="issuer is required"):
        IdentityAssertionOAuthProvider(
            server_url=f"{RS}/mcp",
            storage=InMemoryStorage(),
            client_id="c",
            client_secret="s",
            issuer="",
            assertion_provider=assertion_provider,
        )


def test_origin_normalizes_default_ports() -> None:
    """`_origin` treats an explicit scheme-default port as equal to the port-less form."""
    assert _origin("https://host") == _origin("https://host:443")
    assert _origin("http://host") == _origin("http://host:80")
    assert _origin("https://host") != _origin("https://host:8443")
    assert _origin("https://host") != _origin("https://other")
