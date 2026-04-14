# Authorization

MCP HTTP transports authenticate via `httpx.Auth`. The SDK provides two
implementations that plug into the same `auth` parameter:

- **`BearerAuth`** — a minimal two-method provider for API keys, gateway-managed
  tokens, service accounts, or any scenario where the token comes from an
  external pipeline.
- **`OAuthClientProvider`** — full OAuth 2.1 authorization-code flow with PKCE,
  Protected Resource Metadata discovery (RFC 9728), dynamic client registration,
  and automatic token refresh.

Both are `httpx.Auth` subclasses. Pass either to `Client(url, auth=...)`,
`streamable_http_client(url, auth=...)`, or directly to
`httpx.AsyncClient(auth=...)`.

## Bearer tokens

For a static token (API key, pre-provisioned credential):

```python
from mcp.client import Client
from mcp.client.auth import BearerAuth

async with Client("https://api.example.com/mcp", auth=BearerAuth("my-api-key")) as client:
    tools = await client.list_tools()
```

For a dynamic token (environment variable, cache, external service), pass a
callable — sync or async:

```python
import os
from mcp.client.auth import BearerAuth

auth = BearerAuth(lambda: os.environ.get("MCP_TOKEN"))
```

`token()` is called before every request, so the callable can return a freshly
rotated value each time. Keep it fast — return a cached value and refresh in the
background rather than blocking on network calls.

### Handling 401

By default, `BearerAuth` raises `UnauthorizedError` immediately on 401. To
refresh credentials and retry once, pass an `on_unauthorized` handler:

```python
from mcp.client.auth import BearerAuth, UnauthorizedContext

token_cache = TokenCache()

async def refresh(ctx: UnauthorizedContext) -> None:
    # ctx.response.headers["WWW-Authenticate"] has scope/resource_metadata hints
    await token_cache.invalidate()

auth = BearerAuth(token_cache.get, on_unauthorized=refresh)
```

After `on_unauthorized` returns, `token()` is called again and the request is
retried once. If the retry also gets 401, `UnauthorizedError` is raised. Retry
state is scoped per-request — a failed retry on one request does not block
retries on subsequent requests.

To abort without retrying (for example, when interactive user action is
required), raise from the handler:

```python
async def signal_host(ctx: UnauthorizedContext) -> None:
    ui.show_reauth_prompt()
    raise UnauthorizedError("User action required before retry")
```

### Subclassing

For more complex providers, subclass `BearerAuth` and override `token()` and
`on_unauthorized()`:

```python
from mcp.client.auth import BearerAuth, UnauthorizedContext

class MyAuth(BearerAuth):
    async def token(self) -> str | None:
        return await self._store.get_access_token()

    async def on_unauthorized(self, context: UnauthorizedContext) -> None:
        await self._store.refresh()
```

## OAuth 2.1

For the full OAuth authorization-code flow with PKCE — including Protected
Resource Metadata discovery, authorization server metadata discovery, dynamic
client registration, and automatic token refresh — use `OAuthClientProvider`:

```python
import httpx
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

auth = OAuthClientProvider(
    server_url="https://api.example.com",
    client_metadata=OAuthClientMetadata(
        client_name="My MCP Client",
        redirect_uris=["http://localhost:3000/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    ),
    storage=my_token_storage,
    redirect_handler=open_browser,
    callback_handler=wait_for_callback,
)

async with streamable_http_client("https://api.example.com/mcp", auth=auth) as (read, write):
    ...
```

See `examples/snippets/clients/oauth_client.py` for a complete working example.

### Non-interactive grants

For machine-to-machine authentication without a browser redirect, use the
extensions in `mcp.client.auth.extensions`:

- `ClientCredentialsOAuthProvider` — `client_credentials` grant with client ID
  and secret
- `PrivateKeyJWTOAuthProvider` — `client_credentials` with `private_key_jwt`
  client authentication (RFC 7523)

## Custom `httpx.Auth`

Any `httpx.Auth` implementation works. To combine authentication with custom
HTTP settings (headers, timeouts, proxies), configure an `httpx.AsyncClient`
directly:

```python
import httpx
from mcp.client.streamable_http import streamable_http_client

http_client = httpx.AsyncClient(
    auth=my_auth,
    headers={"X-Custom": "value"},
    timeout=httpx.Timeout(60.0),
)

async with http_client:
    async with streamable_http_client(url, http_client=http_client) as (read, write):
        ...
```
