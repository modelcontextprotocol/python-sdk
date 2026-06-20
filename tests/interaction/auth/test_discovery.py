"""Protected-resource and authorization-server metadata discovery, end to end.

Every client-side test connects a real `Client` via `connect_with_oauth` and asserts on the
recorded request paths the discovery probes produced; the discovery URL ordering is a wire
detail `Client` cannot observe directly but the recording can. Tests that need a metadata
endpoint to 404 or return alternate content wrap the SDK's app in `shimmed_app` while leaving
the real authorize and token endpoints behind it, so the rest of the flow runs unaltered.

The two server-side tests (#5, #6) drive raw httpx against `mounted_app` because their
assertions are the metadata response bodies and headers, which `Client` does not surface.
"""

import json

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl

from mcp import types
from mcp.client.auth import OAuthFlowError, OAuthRegistrationError
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from mcp.types import ListToolsResult, Tool
from tests.interaction._connect import BASE_URL, mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    RecordedRequest,
    auth_settings,
    connect_with_oauth,
    metadata_body,
    record_requests,
    shim,
)
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio

PRM_PATH_SUFFIXED = "/.well-known/oauth-protected-resource/mcp"
PRM_ROOT = "/.well-known/oauth-protected-resource"
ASM_ROOT = "/.well-known/oauth-authorization-server"
OIDC_ROOT = "/.well-known/openid-configuration"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="probe", input_schema={"type": "object"})])


def discovery_gets(recorded: list[RecordedRequest]) -> list[str]:
    """Return the well-known GET paths in recorded order, ignoring everything else."""
    return [r.path for r in recorded if r.method == "GET" and "/.well-known/" in r.path]


def real_asm() -> OAuthMetadata:
    """Build an authorization-server metadata document pointing at the real co-hosted endpoints."""
    return OAuthMetadata(
        issuer=AnyHttpUrl(BASE_URL),
        authorization_endpoint=AnyHttpUrl(f"{BASE_URL}/authorize"),
        token_endpoint=AnyHttpUrl(f"{BASE_URL}/token"),
        registration_endpoint=AnyHttpUrl(f"{BASE_URL}/register"),
        scopes_supported=["mcp"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
    )


@requirement("client-auth:prm-discovery:fallback-order")
async def test_prm_discovery_uses_the_resource_metadata_url_from_www_authenticate() -> None:
    """The first protected-resource probe is the URL the 401's `WWW-Authenticate` header supplied.

    With co-hosted defaults the header carries the path-suffixed well-known URL; the client
    fetches that one first and, because it succeeds, never falls back. The single-probe
    sequence proves priority 1.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, on_request=on_request) as (client, _):
            await client.list_tools()

    assert discovery_gets(recorded) == snapshot([PRM_PATH_SUFFIXED, ASM_ROOT])
    assert (recorded[0].method, recorded[0].path) == ("POST", "/mcp")
    assert (recorded[1].method, recorded[1].path) == ("GET", PRM_PATH_SUFFIXED)


@requirement("client-auth:prm-discovery:fallback-order")
async def test_prm_discovery_falls_back_from_path_well_known_to_root_on_404() -> None:
    """When the path-suffixed PRM well-known 404s, the client falls back to the root well-known.

    The exact GET count is not asserted: the WWW-Authenticate URL equals the path well-known
    here, so the SDK probes it twice (once as priority 1, once as priority 2) before reaching
    root. Asserting "path before root, root reached, then the flow proceeds" pins the spec
    invariant; the duplicate probe is an implementation detail. The served PRM body carries an
    unrecognized field to prove the client's parser ignores unknown members (RFC 9728 §3.2).
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    prm = ProtectedResourceMetadata(
        resource=AnyHttpUrl(f"{BASE_URL}/mcp"), authorization_servers=[AnyHttpUrl(BASE_URL)]
    )
    app_shim = shim(
        not_found=frozenset({PRM_PATH_SUFFIXED}),
        serve={PRM_ROOT: metadata_body(prm, x_unknown_extension="ignored")},
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request) as (
            client,
            _,
        ):
            await client.list_tools()

    well_known = discovery_gets(recorded)
    assert PRM_PATH_SUFFIXED in well_known
    assert PRM_ROOT in well_known
    assert well_known.index(PRM_PATH_SUFFIXED) < well_known.index(PRM_ROOT)
    assert any(r.path == "/authorize" for r in recorded)


@requirement("client-auth:prm-discovery:no-prm-fallback")
async def test_when_every_prm_probe_fails_the_client_discovers_as_metadata_at_the_server_origin() -> None:
    """When every protected-resource metadata probe 404s, the client falls back to the legacy path.

    The legacy 2025-03-26 behaviour: with no PRM document available, treat the MCP server's
    origin as the authorization server and fetch its `/.well-known/oauth-authorization-server`
    directly. The real co-hosted ASM endpoint is at exactly that location, so the flow completes.
    The recorded sequence shows both PRM well-known paths probed (and failed) before ASM_ROOT.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    app_shim = shim(not_found=frozenset({PRM_PATH_SUFFIXED, PRM_ROOT}))

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request) as (
            client,
            _,
        ):
            result = await client.list_tools()

    well_known = discovery_gets(recorded)
    assert PRM_PATH_SUFFIXED in well_known
    assert PRM_ROOT in well_known
    assert well_known[-1] == ASM_ROOT
    assert all(well_known.index(prm) < well_known.index(ASM_ROOT) for prm in (PRM_PATH_SUFFIXED, PRM_ROOT))
    assert result.tools[0].name == "probe"


@requirement("client-auth:dcr:registration-error-surfaces")
async def test_a_400_from_the_registration_endpoint_surfaces_as_a_registration_error() -> None:
    """A 400 from `/register` surfaces as `OAuthRegistrationError` carrying the server's body.

    The shim makes `/register` return RFC 7591's `invalid_client_metadata`; the SDK reads the
    body and raises with the status and text in the message, before any authorize or token
    request is made.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    error_body = json.dumps({"error": "invalid_client_metadata", "error_description": "no"}).encode()
    app_shim = shim(serve={"/register": (400, error_body)})

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthRegistrationError, match=r"^Registration failed: 400 .*invalid_client_metadata"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request).__aenter__()

    assert [r.path for r in recorded if r.path in ("/authorize", "/token")] == []


@requirement("client-auth:prm-resource-mismatch")
async def test_prm_with_a_mismatched_resource_aborts_the_flow_before_authorize() -> None:
    """A PRM document whose `resource` does not cover the server URL aborts the flow.

    The shim serves PRM at the URL the WWW-Authenticate header supplies, but with a `resource`
    on a different path; `check_resource_allowed` rejects it and `OAuthFlowError` is raised
    before any authorize or token request is made. The error reaches the test wrapped in nested
    single-element exception groups by the streamable-HTTP client's task group.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    prm = ProtectedResourceMetadata(
        resource=AnyHttpUrl(f"{BASE_URL}/other"), authorization_servers=[AnyHttpUrl(BASE_URL)]
    )
    app_shim = shim(serve={PRM_PATH_SUFFIXED: metadata_body(prm)})

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^Protected resource .* does not match expected"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request).__aenter__()

    assert [r.path for r in recorded if r.path in ("/authorize", "/token")] == []


@requirement("client-auth:as-metadata-discovery:priority-order")
@pytest.mark.parametrize(
    ("authorization_server", "not_found", "serve_at", "expected_order"),
    [
        pytest.param(
            f"{BASE_URL}/",
            frozenset({ASM_ROOT}),
            OIDC_ROOT,
            [ASM_ROOT, OIDC_ROOT],
            id="root-issuer",
        ),
        pytest.param(
            f"{BASE_URL}/tenant",
            frozenset({f"{ASM_ROOT}/tenant", f"{OIDC_ROOT}/tenant"}),
            "/tenant/.well-known/openid-configuration",
            [f"{ASM_ROOT}/tenant", f"{OIDC_ROOT}/tenant", "/tenant/.well-known/openid-configuration"],
            id="path-issuer",
        ),
    ],
)
async def test_as_metadata_discovery_falls_back_through_the_spec_endpoint_order(
    authorization_server: str, not_found: frozenset[str], serve_at: str, expected_order: list[str]
) -> None:
    """Authorization-server metadata is fetched at the spec's endpoints in the spec's order.

    The shim 404s every endpoint before the last so the recording proves each probe and its
    position. For an issuer URL with no path the order is OAuth root then OIDC root; for an
    issuer URL with a path component it is OAuth path-inserted, OIDC path-inserted, then OIDC
    path-appended (the spec's three-endpoint MUST). The path-issuer case is driven by serving
    a PRM whose `authorization_servers` carries the path; the SDK's own AS routes stay at root
    (the served body points at the real `/authorize` and `/token`). The served bodies carry an
    unrecognized field to prove the client's parser ignores unknown members (RFC 8414 §3.2).
    """
    recorded, on_request = record_requests()
    asm = real_asm()
    asm.issuer = AnyHttpUrl(authorization_server)
    # The redirect iss must equal the issuer the client records from this metadata.
    provider = InMemoryAuthorizationServerProvider(issuer=str(asm.issuer))
    server = Server("guarded", on_list_tools=list_tools)

    prm = ProtectedResourceMetadata(
        resource=AnyHttpUrl(f"{BASE_URL}/mcp"), authorization_servers=[AnyHttpUrl(authorization_server)]
    )
    app_shim = shim(
        not_found=not_found,
        serve={
            PRM_PATH_SUFFIXED: metadata_body(prm),
            serve_at: metadata_body(asm, x_unknown_extension="ignored"),
        },
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request) as (
            client,
            _,
        ):
            await client.list_tools()

    assert discovery_gets(recorded) == [PRM_PATH_SUFFIXED, *expected_order]


@requirement("hosting:auth:metadata-endpoints")
@requirement("hosting:auth:prm:authorization-servers-field")
async def test_the_prm_endpoint_serves_the_resource_url_and_at_least_one_authorization_server() -> None:
    """The protected-resource metadata document the SDK serves identifies the resource and an authorization server.

    Also asserts the response is `application/json` (RFC 9728 §3.2) and that fields the SDK has
    no value for are absent rather than null (`PydanticJSONResponse` serializes with
    `exclude_none=True`, satisfying RFC 9728 §3.2's omit-zero-value rule).
    """
    server = Server("bare")
    provider = InMemoryAuthorizationServerProvider()

    async with mounted_app(server, auth=auth_settings(), auth_server_provider=provider) as (http, _):
        response = await http.get(PRM_PATH_SUFFIXED)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    document = json.loads(response.content)
    assert "resource_documentation" not in document
    assert "scopes_supported" in document

    metadata = ProtectedResourceMetadata.model_validate(document)
    assert str(metadata.resource).rstrip("/") == f"{BASE_URL}/mcp"
    assert len(metadata.authorization_servers) >= 1
    assert metadata.bearer_methods_supported == ["header"]


@requirement("hosting:auth:as-router")
async def test_as_metadata_advertises_authorize_token_registration_and_s256() -> None:
    """The authorization-server metadata document the SDK serves names the required endpoints and S256."""
    server = Server("bare")
    provider = InMemoryAuthorizationServerProvider()

    async with mounted_app(server, auth=auth_settings(), auth_server_provider=provider) as (http, _):
        response = await http.get(ASM_ROOT)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    metadata = OAuthMetadata.model_validate_json(response.content)
    assert str(metadata.issuer).rstrip("/") == BASE_URL
    assert str(metadata.authorization_endpoint) == f"{BASE_URL}/authorize"
    assert str(metadata.token_endpoint) == f"{BASE_URL}/token"
    assert str(metadata.registration_endpoint) == f"{BASE_URL}/register"
    assert metadata.response_types_supported == ["code"]
    assert metadata.code_challenge_methods_supported is not None
    assert "S256" in metadata.code_challenge_methods_supported


@requirement("client-auth:as-metadata-discovery:issuer-validation")
async def test_as_metadata_with_a_mismatched_issuer_aborts_the_flow() -> None:
    """Authorization-server metadata whose `issuer` does not match the discovery URL is rejected.

    RFC 8414 §3.3 / SEP-2468 require the client to reject the document; the SDK compares `issuer`
    to the URL the metadata was fetched from and raises `OAuthFlowError` before any authorize or
    token request is made.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    metadata = real_asm()
    metadata.issuer = AnyHttpUrl(f"{BASE_URL}/wrong-issuer")
    app_shim = shim(serve={ASM_ROOT: metadata_body(metadata)})

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^Authorization server metadata issuer mismatch"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(server, provider=provider, app_shim=app_shim, on_request=on_request).__aenter__()

    assert [r.path for r in recorded if r.path in ("/authorize", "/token")] == []
