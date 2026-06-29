"""Error-plane behaviour of the SDK's bundled OAuth authorization-server handlers, driven with raw httpx.

Where the pinned output deviates from the OAuth RFCs, the manifest entry carries the divergence.
"""

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from inline_snapshot import snapshot

from mcp.server import Server
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.shared.auth import OAuthClientInformationFull
from tests.interaction._connect import mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import REDIRECT_URI, auth_settings, oauth_client_metadata
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
async def as_app() -> AsyncIterator[tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider]]:
    provider = InMemoryAuthorizationServerProvider()
    settings = auth_settings()
    async with mounted_app(
        Server("guarded"),
        auth=settings,
        token_verifier=ProviderTokenVerifier(provider),
        auth_server_provider=provider,
    ) as (http, _):
        yield http, provider


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def _register_client(http: httpx.AsyncClient) -> OAuthClientInformationFull:
    response = await http.post("/register", content=oauth_client_metadata().model_dump_json())
    assert response.status_code == 201
    return OAuthClientInformationFull.model_validate_json(response.content)


async def _mint_code(http: httpx.AsyncClient) -> tuple[OAuthClientInformationFull, str, str]:
    client_info = await _register_client(http)
    assert client_info.client_id is not None
    verifier, challenge = _pkce_pair()
    response = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    redirect = urlsplit(response.headers["location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT_URI
    code = parse_qs(redirect.query)["code"][0]
    return client_info, code, verifier


def _token_form(client_info: OAuthClientInformationFull, **overrides: str) -> dict[str, str]:
    assert client_info.client_id is not None
    assert client_info.client_secret is not None
    form = {
        "grant_type": "authorization_code",
        "client_id": client_info.client_id,
        "client_secret": client_info.client_secret,
        "redirect_uri": REDIRECT_URI,
    }
    form.update(overrides)
    return form


@requirement("hosting:auth:as:authorize-requires-pkce")
async def test_authorize_without_a_code_challenge_is_rejected_with_invalid_request(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """PKCE is mandatory by construction: `code_challenge` is a required field of the authorize handler,
    so a code without a stored challenge can never be issued and PKCE downgrade needs no separate test."""
    http, _ = as_app
    client_info = await _register_client(http)
    assert client_info.client_id is not None

    response = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": REDIRECT_URI,
            "state": "abc",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect = urlsplit(response.headers["location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT_URI
    params = parse_qs(redirect.query)
    assert params["error"] == ["invalid_request"]
    assert params["state"] == ["abc"]
    assert "code_challenge" in params["error_description"][0]


@requirement("hosting:auth:as:verifier-mismatch")
async def test_a_mismatched_code_verifier_is_rejected_with_invalid_grant(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    http, _ = as_app
    client_info, code, _ = await _mint_code(http)

    response = await http.post("/token", data=_token_form(client_info, code=code, code_verifier="0" * 64))

    assert response.status_code == 400
    assert response.json() == snapshot({"error": "invalid_grant", "error_description": "incorrect code_verifier"})


@requirement("hosting:auth:as:code-single-use")
async def test_reusing_an_authorization_code_is_rejected_with_invalid_grant(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """Single-use comes from the handler (`invalid_grant` when `load_authorization_code` returns None)
    plus the provider deleting the code on first exchange — a non-consuming provider loses the guarantee."""
    http, _ = as_app
    client_info, code, verifier = await _mint_code(http)
    form = _token_form(client_info, code=code, code_verifier=verifier)

    first = await http.post("/token", data=form)
    assert first.status_code == 200
    assert first.json()["token_type"] == "Bearer"

    second = await http.post("/token", data=form)
    assert second.status_code == 400
    assert second.json() == snapshot(
        {"error": "invalid_grant", "error_description": "authorization code does not exist"}
    )


@requirement("hosting:auth:as:redirect-uri-binding")
async def test_a_redirect_uri_differing_from_authorize_is_rejected_at_the_token_endpoint(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """RFC 6749 §5.2 specifies `invalid_grant` here; the SDK returns `invalid_request` (see the
    divergence on the requirement). The rejection itself — an intercepted code cannot be redeemed
    without the original authorize redirect URI — is the security property."""
    http, _ = as_app
    client_info, code, verifier = await _mint_code(http)

    response = await http.post(
        "/token",
        data=_token_form(client_info, code=code, code_verifier=verifier, redirect_uri=f"{REDIRECT_URI}/different"),
    )

    assert response.status_code == 400
    assert response.json() == snapshot(
        {
            "error": "invalid_request",
            "error_description": "redirect_uri did not match the one used when creating auth code",
        }
    )


@requirement("hosting:auth:as:token-cache-headers")
async def test_token_responses_carry_cache_control_no_store(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    http, _ = as_app
    client_info, code, verifier = await _mint_code(http)
    form = _token_form(client_info, code=code, code_verifier=verifier)

    success = await http.post("/token", data=form)
    assert success.status_code == 200
    assert success.headers["cache-control"] == "no-store"
    assert success.headers["pragma"] == "no-cache"

    failure = await http.post("/token", data=form)
    assert failure.status_code == 400
    assert failure.headers["cache-control"] == "no-store"
    assert failure.headers["pragma"] == "no-cache"


@requirement("hosting:auth:as:register-error-response")
async def test_registration_with_invalid_metadata_is_rejected_with_400(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """Invalid client metadata at the registration endpoint returns 400 with an RFC 7591 error body."""
    http, _ = as_app

    malformed = await http.post("/register", json={"redirect_uris": ["not-a-url"]})
    assert malformed.status_code == 400
    assert malformed.json()["error"] == "invalid_client_metadata"

    body = oauth_client_metadata().model_dump(mode="json", exclude_none=True)

    no_auth_code = await http.post("/register", json=body | {"grant_types": ["refresh_token"]})
    assert no_auth_code.status_code == 400
    assert no_auth_code.json() == snapshot(
        {"error": "invalid_client_metadata", "error_description": "grant_types must include 'authorization_code'"}
    )

    bad_scope = await http.post("/register", json=body | {"scope": "forbidden"})
    assert bad_scope.status_code == 400
    body = bad_scope.json()
    assert body["error"] == "invalid_client_metadata"
    # The description embeds a set difference whose ordering is not stable, so assert the prefix.
    assert body["error_description"].startswith("Requested scopes are not valid: ")


@requirement("hosting:auth:as:redirect-uri-binding")
async def test_authorize_with_an_unregistered_redirect_uri_is_rejected_directly(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """The server never redirects to an unvalidated URI: a direct JSON error, not a 302 to the attacker."""
    http, _ = as_app
    client_info = await _register_client(http)
    assert client_info.client_id is not None
    _, challenge = _pkce_pair()

    response = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": "http://127.0.0.1:8000/evil",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "location" not in response.headers
    body = response.json()
    assert body["error"] == "invalid_request"
    assert "not registered" in body["error_description"]


@requirement("hosting:auth:as:redirect-uri-scheme")
async def test_a_non_loopback_http_redirect_uri_is_accepted_at_registration(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """The spec requires redirect URIs to be HTTPS or loopback; the bundled registration handler does
    not enforce this (see the divergence on the requirement)."""
    http, provider = as_app
    body = oauth_client_metadata().model_dump(mode="json", exclude_none=True)
    body["redirect_uris"] = ["http://evil.example/callback"]

    response = await http.post("/register", json=body)

    assert response.status_code == 201
    info = OAuthClientInformationFull.model_validate_json(response.content)
    assert [str(u) for u in (info.redirect_uris or [])] == ["http://evil.example/callback"]
    assert info.client_id in provider.clients
