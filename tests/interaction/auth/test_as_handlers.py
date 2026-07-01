"""Error-plane behaviour of the SDK's bundled OAuth authorization-server handlers.

The end-to-end OAuth tests prove the handlers' happy paths; these tests drive the same
mounted authorization server directly with raw httpx so the assertions are the HTTP
semantics (status, redirect target, error body, headers) the OAuth RFCs mandate. Almost
every behaviour here is enforced by the SDK's own handlers; where the pinned output
deviates from the RFC, the manifest entry carries the divergence.
"""

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import AnyUrl

from mcp.server import Server
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from tests.interaction._connect import mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import REDIRECT_URI, auth_settings, oauth_client_metadata
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
async def as_app() -> AsyncIterator[tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider]]:
    """Co-host the SDK's authorization-server routes and yield a raw httpx client against them."""
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
    """Generate a (code_verifier, code_challenge) pair the same way the SDK client does."""
    verifier = secrets.token_urlsafe(48)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def _register_client(http: httpx.AsyncClient) -> OAuthClientInformationFull:
    """Dynamically register a client and return its full credentials."""
    response = await http.post("/register", content=oauth_client_metadata().model_dump_json())
    assert response.status_code == 201
    return OAuthClientInformationFull.model_validate_json(response.content)


async def _mint_code(http: httpx.AsyncClient) -> tuple[OAuthClientInformationFull, str, str]:
    """Register a client, complete a valid authorize step, and return (client_info, code, verifier)."""
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
    """Build the form body for an authorization-code token request, with the defaults a real client would send."""
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
    """An authorize request omitting `code_challenge` is redirected back with `error=invalid_request`.

    PKCE is mandatory: the bundled authorize handler models `code_challenge` as a required field, so
    a code without a stored challenge can never be issued. That makes the PKCE-downgrade attack (a
    token request carrying a verifier for a code minted without a challenge) structurally impossible
    through these handlers, so no separate downgrade-guard test is needed.
    """
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
    """A token exchange whose `code_verifier` does not hash to the stored challenge is rejected."""
    http, _ = as_app
    client_info, code, _ = await _mint_code(http)

    response = await http.post("/token", data=_token_form(client_info, code=code, code_verifier="0" * 64))

    assert response.status_code == 400
    assert response.json() == snapshot({"error": "invalid_grant", "error_description": "incorrect code_verifier"})


@requirement("hosting:auth:as:code-single-use")
async def test_reusing_an_authorization_code_is_rejected_with_invalid_grant(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """An authorization code can be exchanged exactly once; a second exchange is `invalid_grant`.

    The handler does not track used codes itself: it returns `invalid_grant` whenever the provider's
    `load_authorization_code` returns None, and the in-memory provider deletes the code on first
    exchange. The test proves the combination enforces single-use; a provider that did not consume
    codes would not get this guarantee from the handler.
    """
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
    """A token exchange whose `redirect_uri` differs from the one used at authorize is rejected.

    This is the security-critical half of redirect-URI binding: a code intercepted via redirect
    substitution cannot be redeemed because the attacker cannot reproduce the original authorize
    redirect URI at the token endpoint. RFC 6749 §5.2 specifies `invalid_grant` for this case;
    the SDK returns `invalid_request` (see the divergence on the requirement). The rejection
    itself is the security property and is correct.
    """
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
    """Every token-endpoint response (success and error) carries `Cache-Control: no-store`."""
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
    """An authorize request naming an unregistered `redirect_uri` returns 400 without redirecting to it.

    The security property is that the authorization server never redirects to an unvalidated URI:
    the response is a direct JSON error to the user agent, not a 302 to the attacker's host.
    """
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
    """A registration carrying a non-HTTPS, non-loopback redirect URI is accepted.

    The spec requires every redirect URI to be either HTTPS or a loopback host; the bundled
    registration handler does not enforce this and registers `http://evil.example/callback`
    successfully. See the divergence on the requirement.
    """
    http, provider = as_app
    body = oauth_client_metadata().model_dump(mode="json", exclude_none=True)
    body["redirect_uris"] = ["http://evil.example/callback"]

    response = await http.post("/register", json=body)

    assert response.status_code == 201
    info = OAuthClientInformationFull.model_validate_json(response.content)
    assert [str(u) for u in (info.redirect_uris or [])] == ["http://evil.example/callback"]
    assert info.client_id in provider.clients


@requirement("hosting:auth:as:register-echo-application-type")
async def test_register_echoes_native_for_a_client_that_registered_application_type_web(
    as_app: tuple[httpx.AsyncClient, InMemoryAuthorizationServerProvider],
) -> None:
    """A client registering `application_type: "web"` is told `"native"` in the registration echo.

    When the passthrough fix lands: re-pin the echo to `"web"` and delete the Divergence.
    """
    http, _ = as_app
    metadata = OAuthClientMetadata(
        client_name="interaction-suite", redirect_uris=[AnyUrl(REDIRECT_URI)], application_type="web"
    )

    response = await http.post("/register", content=metadata.model_dump_json())

    assert response.status_code == 201
    body = response.json()
    assert body["application_type"] == "native"
    # The omission is specific to application_type, not a generally lossy echo.
    assert body["client_name"] == "interaction-suite"
