"""`docs/advanced/oauth-clients.md`: every claim the page makes, proved against the real SDK."""

import inspect

import httpx
import pytest
from pydantic import AnyUrl, ValidationError

from docs_src.oauth_clients import tutorial001, tutorial002
from mcp.client.auth import OAuthClientProvider, OAuthFlowError, OAuthRegistrationError, OAuthTokenError, TokenStorage
from mcp.client.auth.extensions.client_credentials import (
    PrivateKeyJWTOAuthProvider,
    RFC7523OAuthClientProvider,  # pyright: ignore[reportDeprecated]
    static_assertion_provider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.shared.exceptions import MCPDeprecationWarning

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_in_memory_storage_satisfies_the_token_storage_protocol() -> None:
    """tutorial001: `TokenStorage` is a Protocol: four async methods, no base class."""
    storage: TokenStorage = tutorial001.InMemoryTokenStorage()
    assert await storage.get_tokens() is None
    assert await storage.get_client_info() is None


async def test_storage_round_trips_tokens_and_client_info() -> None:
    """tutorial001: whatever the provider stores, it gets back: the whole persistence contract."""
    storage = tutorial001.InMemoryTokenStorage()
    tokens = OAuthToken(access_token="at-123", refresh_token="rt-456", expires_in=3600, scope="user")
    client_info = OAuthClientInformationFull(
        client_id="generated-by-the-as",
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
    )
    await storage.set_tokens(tokens)
    await storage.set_client_info(client_info)
    assert await storage.get_tokens() == tokens
    assert await storage.get_client_info() == client_info


async def test_the_provider_is_an_httpx_auth() -> None:
    """tutorial001: `OAuthClientProvider` plugs into httpx, not into MCP."""
    assert isinstance(tutorial001.oauth, httpx.Auth)


async def test_the_metadata_defaults_are_the_authorization_code_flow() -> None:
    """tutorial001: `grant_types` and `response_types` default to code + refresh: nothing to set."""
    metadata = tutorial001.oauth.context.client_metadata
    assert metadata.grant_types == ["authorization_code", "refresh_token"]
    assert metadata.response_types == ["code"]


async def test_redirect_uris_is_required() -> None:
    """The `!!! check`: registration metadata is validated locally, before any network."""
    with pytest.raises(ValidationError, match="redirect_uris\n  Field required"):
        OAuthClientMetadata.model_validate({"client_name": "Bookshop Agent"})


async def test_the_redirect_handler_receives_the_authorization_url(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial001: `redirect_handler` is the one place the authorization URL surfaces."""
    await tutorial001.open_browser("https://auth.example.com/authorize?client_id=abc")
    assert capsys.readouterr().out == "Visit: https://auth.example.com/authorize?client_id=abc\n"


async def test_client_credentials_provider_has_no_human_in_the_loop() -> None:
    """tutorial002: `ClientCredentialsOAuthProvider` is the same `httpx.Auth`, minus the handlers."""
    assert isinstance(tutorial002.oauth, OAuthClientProvider)
    assert isinstance(tutorial002.oauth, httpx.Auth)
    assert tutorial002.oauth.context.redirect_handler is None
    assert tutorial002.oauth.context.callback_handler is None


async def test_client_credentials_provider_builds_its_own_metadata() -> None:
    """tutorial002: the grant is `client_credentials`, there is nothing to redirect to."""
    metadata = tutorial002.oauth.context.client_metadata
    assert metadata.grant_types == ["client_credentials"]
    assert metadata.token_endpoint_auth_method == "client_secret_basic"
    assert metadata.redirect_uris is None
    assert metadata.scope == "user"


async def test_the_three_remaining_keyword_arguments_have_defaults() -> None:
    """The page names `timeout`, `client_metadata_url` and `validate_resource_url` as the remainder."""
    parameters = inspect.signature(OAuthClientProvider.__init__).parameters
    supplied = ["server_url", "client_metadata", "storage", "redirect_handler", "callback_handler"]
    remainder = ["timeout", "client_metadata_url", "validate_resource_url"]
    assert list(parameters) == ["self", *supplied, *remainder]
    assert all(parameters[name].default is not inspect.Parameter.empty for name in remainder)


async def test_the_one_more_provider_is_private_key_jwt() -> None:
    """The `!!! info`: `PrivateKeyJWTOAuthProvider` is the same `httpx.Auth`, built the same way."""
    provider = PrivateKeyJWTOAuthProvider(
        server_url="http://localhost:8001/mcp",
        storage=tutorial002.InMemoryTokenStorage(),
        client_id="reporting-agent",
        assertion_provider=static_assertion_provider("a.prebuilt.jwt"),
    )
    assert isinstance(provider, OAuthClientProvider)
    assert isinstance(provider, httpx.Auth)
    assert provider.context.client_metadata.token_endpoint_auth_method == "private_key_jwt"


async def test_the_page_does_not_count_the_deprecated_provider() -> None:
    """Why the `!!! info` says *one* more provider: `RFC7523OAuthClientProvider` warns on construction."""
    with pytest.warns(MCPDeprecationWarning, match="RFC7523OAuthClientProvider is deprecated"):
        RFC7523OAuthClientProvider(  # pyright: ignore[reportDeprecated]
            server_url="http://localhost:8001/mcp",
            client_metadata=tutorial001.oauth.context.client_metadata,
            storage=tutorial001.InMemoryTokenStorage(),
        )


async def test_every_oauth_error_is_an_oauth_flow_error() -> None:
    """Catch `OAuthFlowError` and you have caught registration and token failures too."""
    assert issubclass(OAuthRegistrationError, OAuthFlowError)
    assert issubclass(OAuthTokenError, OAuthFlowError)


async def test_not_everything_is_a_flow_error() -> None:
    """A bad argument is a `ValueError`, not an `OAuthFlowError`: the page says *OAuth* failures."""
    with pytest.raises(ValueError, match="client_metadata_url must be a valid HTTPS URL") as exc_info:
        OAuthClientProvider(
            server_url="http://localhost:8001/mcp",
            client_metadata=tutorial001.oauth.context.client_metadata,
            storage=tutorial001.InMemoryTokenStorage(),
            client_metadata_url="http://not-https.example/client.json",
        )
    assert not isinstance(exc_info.value, OAuthFlowError)
