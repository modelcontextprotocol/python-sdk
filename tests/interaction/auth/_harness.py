"""In-process harness for the auth interaction tests.

Co-hosts the SDK's authorization-server routes, protected-resource metadata route, and the
bearer-gated MCP endpoint on one Starlette app via `Server.streamable_http_app(auth=...,
token_verifier=..., auth_server_provider=...)`, drives that app through the streaming bridge
on a single `httpx.AsyncClient` carrying `auth=OAuthClientProvider(...)`, and completes the
authorize redirect headlessly by GETing the URL through the same bridge and parsing the code
from the 302 `Location`. The whole authorization-code flow runs in one event loop with no
sockets, no threads, and no real time.
"""

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
from pydantic import AnyHttpUrl, AnyUrl, BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.client.auth import OAuthClientProvider
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.auth.provider import AccessToken, ProviderTokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from tests.interaction._connect import BASE_URL, NO_DNS_REBINDING_PROTECTION
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider
from tests.interaction.transports._bridge import StreamingASGITransport

REDIRECT_URI = f"{BASE_URL}/oauth/callback"

AppShim = Callable[[ASGIApp], ASGIApp]


@dataclass
class RecordedRequest:
    """A snapshot of an `httpx.Request` at the moment it was sent.

    The auth flow re-yields the same `httpx.Request` object after mutating its headers in
    place for the retry, so tests that need to assert on the first attempt's headers must
    capture a copy rather than a live reference. `record_requests` produces these.
    """

    method: str
    url: httpx.URL
    headers: dict[str, str]
    content: bytes

    @property
    def path(self) -> str:
        return self.url.path


def record_requests() -> tuple[list[RecordedRequest], Callable[[httpx.Request], None]]:
    """Build an `on_request` callback that snapshots each request, and the list it appends to."""
    recorded: list[RecordedRequest] = []

    def on_request(request: httpx.Request) -> None:
        recorded.append(
            RecordedRequest(
                method=request.method,
                url=request.url,
                headers=dict(request.headers),
                content=bytes(request.content),
            )
        )

    return recorded, on_request


def metadata_body(model: BaseModel, **extra: object) -> bytes:
    """Serialize a metadata model to a JSON body for `shimmed_app(serve=...)`.

    `extra` keys are merged into the serialized object so a test can inject fields the model
    does not declare (e.g. an unknown extension field, to prove the client's parser tolerates
    unrecognized members per RFC 8414/9728 §3.2). The model itself would silently drop such
    fields at construction, so they have to be added after serialization.
    """
    document = model.model_dump(by_alias=True, mode="json", exclude_none=True)
    document.update(extra)
    return json.dumps(document).encode()


class StaticTokenVerifier:
    """A `TokenVerifier` backed by a fixed token→`AccessToken` mapping.

    Any token string not in the mapping verifies to `None`, which the bearer middleware treats
    as an unrecognized token. Tests seed the mapping with the exact token shapes (valid, expired,
    wrong scope, wrong audience) they need so the resource-server gate's behaviour is asserted in
    isolation from the authorization-server provider.
    """

    def __init__(self, tokens: Mapping[str, AccessToken]) -> None:
        self._tokens = dict(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._tokens.get(token)


class InMemoryTokenStorage:
    """A `TokenStorage` that holds tokens and client info as instance attributes.

    Tests pre-seed `client_info` (via the constructor or by assignment) to drive the
    pre-registered path, and read both attributes after the flow to assert what the SDK
    persisted.
    """

    def __init__(self, *, client_info: OAuthClientInformationFull | None = None) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = client_info

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class HeadlessOAuth:
    """Completes the authorize step in-process by following the redirect through the bridge.

    `redirect_handler` GETs the authorize URL on the bound client (with `auth=None` so the
    request does not re-enter the locked auth flow), parses `code` and `state` from the 302
    `Location`, and stashes them; `callback_handler` returns the stashed pair. Tests inspect
    `authorize_url` to assert what the SDK put on the authorize request, and `iss`/`error` to
    assert what the redirect carried.

    `state_override`: when set, `callback_handler` returns this value as the state instead of
    the one parsed from the redirect, so tests can drive the state-mismatch path.

    `iss_override`: when set, `callback_handler` returns this value as the RFC 9207 issuer
    instead of the one parsed from the redirect, so tests can drive the iss-mismatch path.

    `code_override`: when set, returned as the code instead of the parsed one (token-endpoint rejection path).
    `omit_iss`: when set, no iss is returned, overriding everything (`iss_override` cannot express absence).
    """

    def __init__(
        self,
        *,
        state_override: str | None = None,
        iss_override: str | None = None,
        code_override: str | None = None,
        omit_iss: bool = False,
    ) -> None:
        self.authorize_url: str | None = None
        self.authorize_urls: list[str] = []
        self.error: str | None = None
        self.iss: str | None = None
        self._state_override = state_override
        self._iss_override = iss_override
        self._code_override = code_override
        self._omit_iss = omit_iss
        self._http: httpx.AsyncClient | None = None
        self._code: str = ""
        self._state: str | None = None

    def bind(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def redirect_handler(self, authorization_url: str) -> None:
        assert self._http is not None
        self.authorize_url = authorization_url
        self.authorize_urls.append(authorization_url)
        # auth=None is load-bearing: without it the GET re-enters OAuthClientProvider.async_auth_flow
        # through its context lock and the flow deadlocks.
        response = await self._http.get(authorization_url, follow_redirects=False, auth=None)
        assert response.status_code == 302, f"authorize endpoint returned {response.status_code}: {response.text}"
        params = parse_qs(urlsplit(response.headers["location"]).query)
        self._code = params.get("code", [""])[0]
        self._state = params.get("state", [None])[0]
        self.iss = params.get("iss", [None])[0]
        self.error = params.get("error", [None])[0]

    async def callback_handler(self) -> AuthorizationCodeResult:
        iss = self._iss_override if self._iss_override is not None else self.iss
        return AuthorizationCodeResult(
            code=self._code_override if self._code_override is not None else self._code,
            state=self._state_override if self._state_override is not None else self._state,
            iss=None if self._omit_iss else iss,
        )


def auth_settings(
    *,
    required_scopes: Sequence[str] = ("mcp",),
    valid_scopes: Sequence[str] | None = None,
    identity_assertion_enabled: bool = False,
) -> AuthSettings:
    """Build `AuthSettings` for the co-hosted authorization + resource server.

    The issuer and resource URLs use the suite's loopback origin, which `validate_issuer_url`
    accepts in lieu of HTTPS. Dynamic client registration is enabled. `valid_scopes` defaults
    to `required_scopes` so a client requesting exactly those passes registration scope
    validation; tests pass a wider set when they need the protected-resource metadata's
    `scopes_supported` (which mirrors `required_scopes`) to differ from what the client may
    register or when AS metadata should advertise additional scopes such as `offline_access`.

    `identity_assertion_enabled` advertises and accepts the SEP-990 ID-JAG grant (RFC 7523
    jwt-bearer); the provider must implement `exchange_identity_assertion` for the endpoint to
    issue tokens.
    """
    required = list(required_scopes)
    valid = list(valid_scopes) if valid_scopes is not None else required
    return AuthSettings(
        issuer_url=AnyHttpUrl(BASE_URL),
        resource_server_url=AnyHttpUrl(f"{BASE_URL}/mcp"),
        required_scopes=required,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=valid, default_scopes=required
        ),
        revocation_options=RevocationOptions(enabled=False),
        identity_assertion_enabled=identity_assertion_enabled,
    )


def oauth_client_metadata() -> OAuthClientMetadata:
    """Build the client's registration metadata.

    `scope` is left unset so the SDK's scope-selection strategy chooses one from the server's
    metadata before registration.
    """
    return OAuthClientMetadata(
        client_name="interaction-suite",
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        grant_types=["authorization_code", "refresh_token"],
    )


def shimmed_app(
    app: ASGIApp,
    *,
    not_found: frozenset[str] = frozenset(),
    serve: Mapping[str, bytes | tuple[int, bytes]] | None = None,
) -> ASGIApp:
    """Wrap an ASGI app so specific paths return canned responses before reaching the real app.

    Paths in `serve` return the given body as `application/json` (status 200, or the supplied
    status when the value is a `(status, body)` pair); paths in `not_found` return 404;
    everything else reaches the wrapped app unchanged. Used by the discovery tests to make a
    well-known endpoint 404 or return alternate metadata while keeping the real authorization
    and MCP endpoints behind it.
    """
    overrides: dict[str, tuple[int, bytes]] = {
        path: value if isinstance(value, tuple) else (200, value) for path, value in (serve or {}).items()
    }

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        if path in overrides:
            status, body = overrides[path]
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if path in not_found:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await app(scope, receive, send)

    return wrapped


def shim(
    *, not_found: frozenset[str] = frozenset(), serve: Mapping[str, bytes | tuple[int, bytes]] | None = None
) -> AppShim:
    """Build an `app_shim` for `connect_with_oauth` that applies `shimmed_app` with these overrides."""
    return lambda app: shimmed_app(app, not_found=not_found, serve=serve)


@dataclass
class _FirstChallenge:
    """ASGI shim that answers the first request to a path with 401 + a given WWW-Authenticate.

    Subsequent requests pass through to the wrapped app. Used to make the initial 401 carry
    parameters (such as `scope=`) that the SDK's own bearer middleware cannot be configured
    to emit, so client behaviour driven by those parameters is reachable end to end. Reserve
    this pattern for behaviour the real server cannot be made to produce.
    """

    app: ASGIApp
    path: str
    www_authenticate: str
    _seen: set[str] = field(default_factory=set[str])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self.path and self.path not in self._seen:
            self._seen.add(self.path)
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"www-authenticate", self.www_authenticate.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)


def first_challenge_shim(www_authenticate: str, *, path: str = "/mcp") -> Callable[[ASGIApp], ASGIApp]:
    """Build an `app_shim` that 401s the first request to `path` with the given header value."""
    return lambda app: _FirstChallenge(app, path, www_authenticate)


def step_up_shim(www_authenticate: str, *, on_nth_authenticated_post: int = 2, persist: bool = False) -> AppShim:
    """Build an `app_shim` that 403s the Nth authenticated POST to `/mcp` with the given challenge.

    Subsequent requests pass through. Used to drive the client's `insufficient_scope` step-up
    handling: the SDK's bearer middleware never emits `scope=` in its 403 challenge (see the
    divergence on `hosting:auth:scope-403`), so the test supplies the 403 itself. Reserve this
    pattern for behaviour the real server cannot be made to produce.

    The default `on_nth_authenticated_post=2` targets the `notifications/initialized` POST: the
    first authenticated POST is the auth flow's retry of the original initialize request (yielded
    after the 401 branch, where the generator ends without inspecting the response), so a 403
    there would not reach the step-up handler.

    `persist`: when set, 403s every authenticated POST from the Nth onward, re-challenging the step-up retry.
    """
    seen = 0
    fired = False

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal seen, fired
            if (
                (persist or not fired)
                and scope["type"] == "http"
                and scope["path"] == "/mcp"
                and scope["method"] == "POST"
                and any(name == b"authorization" for name, _ in scope["headers"])
            ):
                seen += 1
                if seen < on_nth_authenticated_post:
                    await app(scope, receive, send)
                    return
                fired = True
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"www-authenticate", www_authenticate.encode())],
                    }
                )
                await send({"type": "http.response.body", "body": b""})
                return
            await app(scope, receive, send)

        return wrapped

    return factory


def m2m_token_shim(provider: InMemoryAuthorizationServerProvider, *, scopes: list[str]) -> AppShim:
    """Build an `app_shim` that handles `grant_type=client_credentials` at `/token`.

    The SDK server's `TokenHandler` only routes `authorization_code` and `refresh_token`, so a
    `client_credentials` request would fail discriminator validation. This shim mints a token via
    `provider.mint_access_token` so the M2M client providers can complete e2e against the real
    bearer middleware. The shim is harness; the SDK-under-test is the client provider, whose
    outbound `/token` body the test asserts. The shim does not authenticate the client (no
    credential check) because the test asserts the credentials on the recorded request, not on
    the server's acceptance.
    """

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and scope["path"] == "/token" and scope["method"] == "POST":
                # The streaming bridge buffers the request body and delivers it in a single
                # http.request event, so one receive is sufficient.
                message = await receive()
                assert not message.get("more_body", False)
                form = dict(parse_qsl(message.get("body", b"").decode()))
                assert form.get("grant_type") == "client_credentials", (
                    f"m2m_token_shim only handles client_credentials; got {form.get('grant_type')!r}"
                )
                access = provider.mint_access_token(client_id="m2m", scopes=scopes, resource=form.get("resource"))
                token = OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=" ".join(scopes))
                response_body = token.model_dump_json(exclude_none=True).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(response_body)).encode()),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": response_body})
                return
            await app(scope, receive, send)

        return wrapped

    return factory


@asynccontextmanager
async def connect_with_oauth(
    server: Server,
    *,
    provider: InMemoryAuthorizationServerProvider,
    settings: AuthSettings | None = None,
    storage: InMemoryTokenStorage | None = None,
    client_metadata: OAuthClientMetadata | None = None,
    client_metadata_url: str | None = None,
    headless: HeadlessOAuth | None = None,
    auth: httpx.Auth | None = None,
    verify_tokens: bool = True,
    app_shim: Callable[[ASGIApp], ASGIApp] | None = None,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> AsyncIterator[tuple[Client, HeadlessOAuth]]:
    """Connect a `Client` to a server's bearer-gated streamable-HTTP app, completing OAuth in process.

    Yields the connected `Client` and the `HeadlessOAuth` whose `authorize_url` records what the
    SDK put on the authorize request. `on_request` records every HTTP request the underlying
    `httpx.AsyncClient` issues, including those yielded from inside the auth flow.

    `headless`: supply a pre-configured `HeadlessOAuth` to override the callback behaviour
    (state mismatch, error redirects). `verify_tokens=False` mounts the MCP endpoint without
    the bearer middleware so a flow driven by a shimmed 401 completes regardless of the granted
    scopes. `app_shim` wraps the built Starlette app before it reaches the bridge transport,
    for tests that need to intercept or rewrite specific server responses.

    `auth`: supply a pre-built `httpx.Auth` (such as `ClientCredentialsOAuthProvider`) to use
    instead of constructing the default `OAuthClientProvider`; in that case `storage`,
    `client_metadata`, `client_metadata_url`, and `headless` are unused (the yielded
    `HeadlessOAuth` is never invoked and its `authorize_url` stays None).
    """
    settings = settings if settings is not None else auth_settings()
    storage = storage if storage is not None else InMemoryTokenStorage()
    client_metadata = client_metadata if client_metadata is not None else oauth_client_metadata()
    headless = headless if headless is not None else HeadlessOAuth()

    oauth = (
        auth
        if auth is not None
        else OAuthClientProvider(
            server_url=f"{BASE_URL}/mcp",
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=headless.redirect_handler,
            callback_handler=headless.callback_handler,
            client_metadata_url=client_metadata_url,
        )
    )

    app: ASGIApp = server.streamable_http_app(
        auth=settings,
        token_verifier=ProviderTokenVerifier(provider) if verify_tokens else None,
        auth_server_provider=provider,
        transport_security=NO_DNS_REBINDING_PROTECTION,
    )
    if app_shim is not None:
        app = app_shim(app)

    event_hooks: dict[str, list[Callable[..., Any]]] | None = None
    if on_request is not None:
        record = on_request

        async def hook(request: httpx.Request) -> None:
            record(request)

        event_hooks = {"request": [hook]}

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(server.session_manager.run())
        http_client = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=StreamingASGITransport(app), base_url=BASE_URL, auth=oauth, event_hooks=event_hooks
            )
        )
        headless.bind(http_client)
        client = await stack.enter_async_context(
            # The auth flow tests snapshot the legacy initialize-handshake HTTP shape.
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client), mode="legacy")
        )
        yield client, headless
