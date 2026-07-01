# OAuth clients

Some MCP servers are protected. Send them a request without a token and they answer `401 Unauthorized`.

**`OAuthClientProvider`** is how you get the token. It is not an MCP object at all. It is an `httpx.Auth`, the standard httpx hook for "do something to every request". You attach it to an `httpx.AsyncClient`, hand that client to the Streamable HTTP transport, and stop thinking about it.

This page is the client side. Making your own server demand a token is **[Authorization](../run/authorization.md)**.

## The provider

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

You give it four things:

* `server_url`: the MCP endpoint you are connecting to. The provider discovers everything else from it.
* `client_metadata`: what you would type into an authorization server's "register an application" form.
* `storage`: where tokens live between runs.
* `redirect_handler` and `callback_handler`: the two moments a human is involved.

Nothing else in the file mentions OAuth. `main()` never sees a token.

### Client metadata

`OAuthClientMetadata` is the real [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) registration document, as a Pydantic model.

You set three fields. The defaults fill in the rest: `grant_types` is already `["authorization_code", "refresh_token"]` and `response_types` is already `["code"]`, which is exactly the flow this provider runs.

!!! check
    Because it is a Pydantic model, it validates **before a single byte goes over the network**.
    Leave out `redirect_uris` and construction fails on the spot with a `ValidationError` that
    names the field:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    No browser opened, no half-finished registration left behind on the authorization server.

### Token storage

**`TokenStorage`** is a `Protocol` with four async methods. You don't inherit from anything; write the methods and any class is a token store:

* `get_tokens` / `set_tokens` hold the `OAuthToken`: access token, refresh token, expiry, scope.
* `get_client_info` / `set_client_info` hold the `OAuthClientInformationFull` the authorization server issued when the provider registered you, including your `client_id`.

The in-memory version above works. It also forgets everything when the process exits, so the next run does the whole dance again. Persist it to a file or your platform's keyring and the next run is silent.

!!! tip
    Store `client_info`, not only the tokens. The provider registers dynamically the first time it
    finds no stored `client_info`. Throw it away and you mint a fresh registration on every run.

### The two handlers

The authorization code flow needs a human exactly once: someone has to sign in and click "allow".

* **`redirect_handler`** is awaited with the fully-built authorization URL. The `client_id`, the `redirect_uri`, the `state` and the PKCE challenge are already in it. Your only job is to get a browser there. A desktop app calls `webbrowser.open`; this file prints it.
* **`callback_handler`** is awaited next. It waits until the user lands back on your `redirect_uri` and returns that redirect's query parameters as an `AuthorizationCodeResult`.

A real client runs a small local HTTP server on the redirect URI instead of calling `input()`. The shape is identical: get redirected, hand back `code`, `state`, and `iss`.

!!! warning
    Pass `state` and `iss` through exactly as they arrived. The provider compares `state` to the one
    it generated and `iss` to the issuer it discovered, and refuses a mismatch. They are the CSRF
    and server-mix-up defences.

### Into the `Client`

Look at `main()`. The provider goes on the **httpx client**, the httpx client goes into `streamable_http_client(url, http_client=...)`, and that transport goes into `Client`.

`streamable_http_client` has no `auth=` keyword. Anything HTTP-level (auth, headers, timeouts, proxies) belongs on the `httpx.AsyncClient` you bring. That layering is **[Client transports](transports.md)**.

## What the provider does for you

The first time `Client` sends a request, the server answers `401`. The provider takes over:

1. **Discovery.** It reads the `WWW-Authenticate` header, fetches the server's Protected Resource Metadata from `/.well-known/oauth-protected-resource`, learns which authorization server protects this resource, and fetches *that* server's metadata.
2. **Registration.** Nothing in storage? It registers you dynamically with your `OAuthClientMetadata` and stores the result.
3. **Authorization.** It generates the PKCE pair and a `state`, builds the authorization URL, awaits your `redirect_handler`, then awaits your `callback_handler` for the code.
4. **Exchange.** It trades the code for an `OAuthToken`, stores it, and replays your original request with `Authorization: Bearer ...`.

After that it is quiet. Tokens come out of storage, an expired access token is refreshed with the refresh token, and only when none of that works does it run the flow again.

You wrote none of it. Three keyword arguments remain (`timeout`, `client_metadata_url` and `validate_resource_url`), and this file needs none of them. `client_metadata_url` is the one worth knowing about; it gets its own section below.

### Try it

Every other example in these docs you can check with an in-memory `Client(server)`. Not this: the whole point of the flow is an HTTP `401`, and there is no HTTP between an in-memory client and its server.

The repository ships the live version. `examples/servers/simple-auth/` runs a standalone authorization server and a protected MCP server; `examples/clients/simple-auth-client/` is this page's client grown into a small CLI. Its README has the two commands: start the servers, run the client against them, and you watch the four steps go by.

## Client ID Metadata Documents

The 2026-07-28 revision of the spec deprecates dynamic client registration in favor of **Client ID Metadata Documents** (CIMD). Instead of POSTing a fresh registration to every authorization server it meets, your client publishes one JSON document about itself at a stable HTTPS URL, and that URL *is* its `client_id`. The authorization server fetches the document; the provider never touches it.

The SDK already speaks it: pass the URL as `client_metadata_url=` when you construct the provider. When the authorization server's metadata advertises `client_id_metadata_document_supported: true`, the provider skips the `/register` request entirely: the URL goes into the flow as the `client_id`, and there is no `client_secret`. When the server doesn't advertise it (most don't yet), or you never pass a URL, the provider falls back to dynamic registration **silently**, and everything above works exactly as described. Stored `client_info` still wins over both.

The URL must be HTTPS with a non-root path; anything else is a `ValueError` at construction, before any network happens. The shipped `examples/clients/simple-auth-client/` takes it as the `MCP_CLIENT_METADATA_URL` environment variable.

## Machine to machine

A nightly job, a CI step, another service. There is no browser and nobody to click "allow". That is the **client credentials** grant: you already hold a `client_id` and a `client_secret`, and the token endpoint is the whole flow.

`ClientCredentialsOAuthProvider` is the same `httpx.Auth`, minus the human:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

What changed:

* No `OAuthClientMetadata`, no handlers. You pass `client_id` and `client_secret`; the provider builds a minimal `client_credentials` registration around them and skips dynamic registration entirely.
* `scopes` is a space-separated string, the OAuth wire format.
* Everything downstream is identical: the same `TokenStorage`, the same `httpx.AsyncClient(auth=...)`, the same `streamable_http_client`.

By default the secret travels as HTTP Basic auth on the token request (`client_secret_basic`). Pass `token_endpoint_auth_method="client_secret_post"` to put it in the form body instead. Some authorization servers only accept one of the two.

!!! tip
    Read `client_secret` from the environment or a secret manager, never from source control.

!!! info
    One more provider lives in `mcp.client.auth.extensions.client_credentials`:
    **`PrivateKeyJWTOAuthProvider`**, for clients that authenticate with a JWT instead of a
    shared secret (`private_key_jwt`, the key-pair and workload-identity flavour). It follows
    the same pattern: construct one, put it on `auth=`. The same module ships
    `SignedJWTParameters` and `static_assertion_provider`, two helpers that build its assertion.

There is one more no-human situation: the client belongs to an enterprise whose identity provider, not the user, decides which MCP servers it may reach. That is a different grant with its own trust model and its own page, **[Identity assertion](identity-assertion.md)**.

## When it fails

When the OAuth flow goes wrong, the provider raises an `OAuthFlowError` from `mcp.client.auth`. It has two subclasses. `OAuthRegistrationError` means the authorization server refused to register you. `OAuthTokenError` means the token endpoint said no. One `except OAuthFlowError:` covers discovery, registration, authorization, and exchange.

Not everything is a flow error. The network can still fail; those are ordinary `httpx` exceptions and pass through untouched.

## Recap

* `OAuthClientProvider` is an `httpx.Auth`. Put it on an `httpx.AsyncClient`, pass that to `streamable_http_client(url, http_client=...)`, and `Client` never knows OAuth happened.
* You supply four things: the server URL, an `OAuthClientMetadata`, a `TokenStorage`, and the redirect/callback handler pair.
* `TokenStorage` is a `Protocol`: four async methods, no base class. Persist `client_info` as well as the tokens.
* Discovery, registration (dynamic, or via a **Client ID Metadata Document**), PKCE, the `state` and `iss` checks, and token refresh are the provider's job, not yours.
* `ClientCredentialsOAuthProvider` is the no-human version: `client_id` + `client_secret`, no handlers, no browser.
* Every OAuth failure is an `OAuthFlowError`; `OAuthRegistrationError` and `OAuthTokenError` are its subclasses.

The other half of this handshake, making your *server* demand the token, is **[Authorization](../run/authorization.md)**.
