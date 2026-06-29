"""In-process harness for the auth interaction tests.

Co-hosts the SDK's authorization-server routes, protected-resource metadata, and bearer-gated MCP
endpoint on one Starlette app, drives it through the streaming bridge, and completes the authorize
redirect headlessly by parsing the code from the 302 `Location` — no sockets, threads, or real time.
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

    The auth flow mutates the request in place for the retry; first-attempt assertions need a copy.
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

    `extra` is merged after serialization (the model would drop unknown fields at construction), so
    tests can inject undeclared members, e.g. to prove parser tolerance per RFC 8414/9728 §3.2.
    """
    document = model.model_dump(by_alias=True, mode="json", exclude_none=True)
    document.update(extra)
    return json.dumps(document).encode()


class StaticTokenVerifier:
    """A `TokenVerifier` backed by a fixed token→`AccessToken` mapping; unknown tokens verify to `None`.

    Tests seed exact token shapes (expired, wrong scope/audience) to assert the resource-server
    gate in isolation from the authorization-server provider.
    """

    def __init__(self, tokens: Mapping[str, AccessToken]) -> None:
        self._tokens = dict(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._tokens.get(token)


class InMemoryTokenStorage:
    """A `TokenStorage` that holds tokens and client info as instance attributes.

    Pre-seed `client_info` for the pre-registered path; read the attributes after the flow to
    assert what the SDK persisted.
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

    `redirect_handler` GETs the authorize URL and parses `code`/`state`/`iss` from the 302
    `Location`; `callback_handler` returns them. `state_override`/`iss_override` replace the
    parsed values to drive the state-mismatch and RFC 9207 iss-mismatch paths.
    """

    def __init__(self, *, state_override: str | None = None, iss_override: str | None = None) -> None:
        self.authorize_url: str | None = None
        self.authorize_urls: list[str] = []
        self.error: str | None = None
        self._state_override = state_override
        self._iss_override = iss_override
        self._http: httpx.AsyncClient | None = None
        self._code: str = ""
        self._state: str | None = None
        self._iss: str | None = None

    def bind(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def redirect_handler(self, authorization_url: str) -> None:
        assert self._http is not None
        self.authorize_url = authorization_url
        self.authorize_urls.append(authorization_url)
        # auth=None is load-bearing: re-entering OAuthClientProvider.async_auth_flow through its lock deadlocks.
        response = await self._http.get(authorization_url, follow_redirects=False, auth=None)
        assert response.status_code == 302, f"authorize endpoint returned {response.status_code}: {response.text}"
        params = parse_qs(urlsplit(response.headers["location"]).query)
        self._code = params.get("code", [""])[0]
        self._state = params.get("state", [None])[0]
        self._iss = params.get("iss", [None])[0]
        self.error = params.get("error", [None])[0]

    async def callback_handler(self) -> AuthorizationCodeResult:
        return AuthorizationCodeResult(
            code=self._code,
            state=self._state_override if self._state_override is not None else self._state,
            iss=self._iss_override if self._iss_override is not None else self._iss,
        )


def auth_settings(
    *,
    required_scopes: Sequence[str] = ("mcp",),
    valid_scopes: Sequence[str] | None = None,
    identity_assertion_enabled: bool = False,
) -> AuthSettings:
    """Build `AuthSettings` for the co-hosted authorization + resource server.

    Issuer/resource URLs use the suite's loopback origin, which `validate_issuer_url` accepts in
    lieu of HTTPS; dynamic client registration is enabled. `valid_scopes` defaults to
    `required_scopes`; pass a wider set when registrable scopes must differ from the metadata's
    `scopes_supported` or the AS should advertise extras like `offline_access`.
    `identity_assertion_enabled` advertises the SEP-990 ID-JAG grant (RFC 7523 jwt-bearer); the
    provider must implement `exchange_identity_assertion`.
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
    """Build registration metadata with `scope` unset so the SDK picks a scope from server metadata."""
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

    Paths in `serve` return the body as `application/json` (200, or a `(status, body)` pair);
    paths in `not_found` return 404. Lets discovery tests 404 or rewrite a well-known endpoint.
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
    """ASGI shim that answers the first request to `path` with 401 + the given `WWW-Authenticate`.

    Lets the initial 401 carry parameters (such as `scope=`) the SDK's bearer middleware cannot be
    configured to emit; reserve this pattern for behaviour the real server cannot produce.
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


def step_up_shim(www_authenticate: str, *, on_nth_authenticated_post: int = 2) -> AppShim:
    """Build an `app_shim` that 403s the Nth authenticated POST to `/mcp` with the given challenge.

    Drives the client's `insufficient_scope` step-up: the SDK's bearer middleware never emits
    `scope=` in its 403 (divergence `hosting:auth:scope-403`), so the test supplies it. The default
    of 2 targets the `notifications/initialized` POST — the first authenticated POST is the auth
    flow's retry, whose response the generator never inspects, so a 403 there would miss the
    step-up handler.
    """
    seen = 0
    fired = False

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal seen, fired
            if (
                not fired
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

    The SDK server's `TokenHandler` only routes `authorization_code` and `refresh_token`, so the
    shim mints the token via `provider.mint_access_token`. The SDK-under-test is the M2M client
    provider; the test asserts credentials on the recorded request, so the shim skips client auth.
    """

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and scope["path"] == "/token" and scope["method"] == "POST":
                # The streaming bridge delivers the whole body in one http.request event; one receive suffices.
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

    The yielded `HeadlessOAuth.authorize_url` records what the SDK put on the authorize request.
    `on_request` sees every HTTP request, including those yielded inside the auth flow.
    `verify_tokens=False` mounts the MCP endpoint without the bearer middleware; `app_shim` wraps
    the built app before it reaches the bridge transport. Passing `auth` replaces the default
    `OAuthClientProvider`; `storage`, `client_metadata`, `client_metadata_url`, and `headless` are
    then unused.
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
