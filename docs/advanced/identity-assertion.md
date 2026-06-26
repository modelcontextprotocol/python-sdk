# Identity assertion

Every provider in **OAuth clients** starts by asking the MCP server a question: *which authorization server do you trust?* It follows the answer wherever it points, and then either a person signs in or a pre-shared secret stands in for one.

An enterprise wants neither decided per server. It already runs an identity provider (Okta, Microsoft Entra ID, your own); the user already signed in to it this morning; and it is the one place the security team wants to decide who may reach what. [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), the **Enterprise-Managed Authorization** extension, moves the decision there. The IdP signs a short-lived JWT, an **Identity Assertion JWT Authorization Grant**, the **ID-JAG**: a statement that *this user*, through *this client*, may reach *this MCP server*. The client trades it for an ordinary access token. No browser, no consent screen, no dynamic registration.

This chapter is both ends of that trade. The MCP server itself never changes: it is still the resource server from **Authorization**, checking whatever token shows up.

## Two token requests

Two different authorities are in play, and naming them apart is most of understanding this page. The **enterprise IdP** is your organization's identity provider: it knows who the employee is, it is where policy lives, and it issues the ID-JAG. The SDK never talks to it. The **MCP authorization server** is the same party it was in **Authorization**: the issuer named in the MCP server's metadata, the thing that mints the tokens that MCP server accepts. In the flows you already know, those two roles are usually one box. Here they are two, and the whole grant is the second agreeing to trust the first.

The client makes one token request to each.

1. **To the enterprise IdP.** The client trades the user's sign-in (their OpenID Connect ID token) for the ID-JAG. This is an RFC 8693 token exchange, it is entirely your IdP's API, and **the SDK does not make it**. You do, inside one async callback. It is also where the policy decision happens: an IdP that says no never issues the ID-JAG, and there is nothing to present.
2. **To the MCP authorization server.** The client presents the ID-JAG under the RFC 7523 `jwt-bearer` grant (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, the ID-JAG as `assertion`) and receives the access token. **This is the request the SDK makes**, and accepting it is the one thing this page adds to an authorization server.

Everything below is the second request: the client that sends it and the authorization server that answers it.

## The client

**`IdentityAssertionOAuthProvider`** lives in `mcp.client.auth.extensions.identity_assertion`. Like every provider in **OAuth clients** it is an `httpx.Auth`: construct one, put it on `auth=`, hand the `httpx.AsyncClient` to the transport.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Read it from the bottom.

* `main()` is the `main()` from **OAuth clients**, line for line. That is the point: once the provider exists, nothing downstream knows which grant produced the token.
* The provider takes what the other providers cannot discover: a `client_id` and `client_secret` somebody **pre-registered** with the authorization server, that authorization server's `issuer`, and `assertion_provider`, an async callback that returns a fresh ID-JAG on demand.
* `storage` is the same `TokenStorage` protocol. Only the two token methods are ever called; there is no dynamic registration here, so there is no `client_info` to remember.

### The assertion provider

`fetch_id_jag(audience, resource)` is the only code you write. It is awaited once per token exchange, never at construction, and only *after* the authorization server's metadata has been fetched and validated, so a misconfigured issuer never leaks an assertion. Its two arguments are two of the claims the ID-JAG must be minted with: `audience` is the authorization server's issuer (the ID-JAG `aud`) and `resource` is the MCP server's canonical identifier (the ID-JAG `resource`). The third is one you already hold: the ID-JAG's `client_id` claim must name the `client_id` you gave the provider, or the authorization server refuses the exchange.

`idp_issue_id_jag` above it is **not your code**. It stands in for the identity provider, signing the assertion in-process so the file is complete and you can read every claim an ID-JAG carries. A real `fetch_id_jag` makes the first token request of the previous section instead: an RFC 8693 token exchange against your IdP, defined by the Identity Assertion JWT Authorization Grant draft that SEP-990 profiles. The signed-in user's ID token goes in as the `subject_token`, the `requested_token_type` is the ID-JAG's own URN (`urn:ietf:params:oauth:token-type:id-jag`), `audience` and `resource` pass straight through, and the response carries the ID-JAG. That exchange, under those names, is what to look for in your IdP's documentation.

!!! tip
    A fresh ID-JAG is requested for every exchange, and that is the point: it is a single-use,
    minutes-lived grant, and the authorization server on this page refuses to accept the same one
    twice. Do not cache it. The access token it buys you is the thing that gets reused.

### The issuer is configuration

Here is the inversion. `OAuthClientProvider` asks the resource server which authorization server to use and follows the answer wherever it points. This provider refuses to: `issuer` is required, the RFC 8414 metadata is fetched from that issuer's own well-known path, the token endpoint must be on that issuer's origin, and the resource server is never asked anything.

The extension does not demand this; it is a deliberately stricter choice. This client carries two things worth stealing, a pre-registered secret and an audience-bound assertion, and a client that let a compromised MCP server steer it to an attacker's authorization server would post both to it. Pinning the issuer at construction deletes that conversation.

!!! warning
    The configured `issuer` is compared to the metadata document's `issuer` field by RFC 8414 §3.3
    simple string comparison: character for character, trailing slash included, no normalization.
    Do not guess it. Fetch `/.well-known/oauth-authorization-server` from your authorization server
    and copy the `issuer` value it returns. For the authorization server on this page that is
    `https://auth.example.com/`, with the slash, because its issuer was built from a pydantic URL
    object. A mismatch stops the flow at `OAuthFlowError: Authorization server metadata issuer
    mismatch` before a single credential or assertion is sent.

### A confidential client

`client_secret` is required; the constructor raises `ValueError` without one. The IETF profile underneath SEP-990 reserves this grant for confidential clients, SEP-990 requires the client to authenticate, and this SDK enforces both by insisting on a shared secret. `token_endpoint_auth_method` picks where it travels: `client_secret_post` (the default, in the form body) or `client_secret_basic` (an HTTP Basic header). The profile also permits `private_key_jwt`; this provider does not support it.

!!! tip
    Read `client_secret` from the environment or a secret manager, never from source control.

### What the provider does for you

The first request goes out unauthenticated, and the server's `401` starts the flow.

1. **Discovery.** It fetches the authorization server metadata from the configured issuer's RFC 8414 well-known path, checks the document's `issuer` matches, and checks the token endpoint is on the issuer's origin.
2. **The assertion.** It awaits your `assertion_provider`.
3. **Exchange.** It POSTs the `jwt-bearer` grant to the token endpoint, stores the `OAuthToken`, and replays your original request with `Authorization: Bearer ...`.

A `403` whose `WWW-Authenticate` names `insufficient_scope` runs steps 2 and 3 again with the union of your `scope` and the challenged one. (`scope` is only ever a request; this page's authorization server grants what the ID-JAG says and nothing else.) There is no refresh token anywhere in this: when the access token expires, the next `401` mints a fresh ID-JAG and exchanges again, and *that* is the lever the IdP holds. Failures are the same two exceptions as the rest of **OAuth clients**: `OAuthFlowError` for discovery and validation, its subclass `OAuthTokenError` when the token endpoint says no.

## The authorization server

Most of the time you stop here. The MCP authorization server is somebody else's product, accepting ID-JAGs is its configuration to turn on, and the SDK's half of SEP-990 is the client above.

The SDK can also *be* the authorization server: `create_auth_routes` returns the authorization server's routes as a list any Starlette app can mount, which is how `examples/servers/simple-auth/` in the repository runs one. SEP-990 adds one flag and one method to that surface:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` gates everything. Off, which is the default, `/token` answers this grant with `unsupported_grant_type` even if you implemented the hook, and the metadata does not mention it. On, the metadata gains the `jwt-bearer` grant type and lists `urn:ietf:params:oauth:grant-profile:id-jag` in `authorization_grant_profiles_supported`, the field the extension uses to advertise support. (This SDK's client never reads it: it is provisioned for one issuer and simply asks.)
* **`exchange_identity_assertion`** is the hook. Before it runs, the SDK has authenticated the client, refused public clients, and refused clients whose registration does not list the grant. You get an `IdentityAssertionParams` (the raw `assertion`, the requested `scopes` and `resource`) and return a plain `OAuthToken`.
* Dynamic client registration refuses this grant unconditionally, so `get_client` here serves a hand-provisioned client. An ID-JAG client cannot register itself into existence.
* Half the class is refusals. `OAuthAuthorizationServerProvider` is the *whole* authorization server, so it also asks for the authorization-code flow; a server that signs users in as well implements those for real, and this one has exactly one door.

!!! warning
    The SDK never decodes the assertion: only your deployment knows which IdP it trusts and which
    keys that IdP publishes, so everything inside `exchange_identity_assertion` is load-bearing.
    Verify the signature against the IdP's published keys (its JWKS; the shared secret here is the
    demo's), and `iss` and `exp`, per RFC 7523 §3. Require the JWT header's `typ` to be
    `oauth-id-jag+jwt`, the profile's guard against some other JWT being replayed as a grant.
    Require `aud` to be your own issuer. Require the ID-JAG's `client_id` claim to equal the client
    the handler authenticated, and its `resource` claim to name a resource you actually serve.
    Track `jti` until the assertion's `exp` so it is accepted once. And take the granted scopes
    and, above all, the issued token's `resource` from the validated ID-JAG, never from the
    request: `params.resource` is whatever the client typed. The full processing rules are in the
    [Enterprise-Managed Authorization specification](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).

Reject a bad assertion with `TokenError("invalid_grant", ...)`. The other error code in this flow is `invalid_target`: an ID-JAG that names a resource you do not serve is refused with it, which is what stops this server minting tokens for somebody else's. And the granted scopes come from the ID-JAG's `scope` claim (an assertion without one is refused too); yours might map the user's groups instead.

And notice what the returned `OAuthToken` does not carry: a refresh token. The IdP decides how long this user keeps access by deciding whether to issue the next ID-JAG. A refresh token minted here would quietly hand that decision back.

!!! info
    A server that still embeds its authorization server with `auth_server_provider=` reaches the same
    code through `AuthSettings(identity_assertion_enabled=True)`. **Authorization** explains why new
    servers should not start there.

!!! check
    Wire the two files on this page together and the whole grant is one `POST /token`:

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    No `/authorize`, no `/register`, no protected-resource-metadata fetch. The only requests on the
    wire are the one that drew the `401`, the well-known fetch, this exchange, and then ordinary
    MCP traffic with the bearer attached. And the `sub` your validator read out of the ID-JAG is
    exactly what `get_access_token().subject` reports inside a tool.

### Try it

`examples/stories/identity_assertion/` in the SDK repository is this page running for real: the same `exchange_identity_assertion` validator, an MCP server gated on its tokens, a stand-in IdP, and the client, in one self-checking program. `uv run python -m stories.identity_assertion.client --http` runs the whole exchange and asserts that the user the IdP named is the user the tool sees.

## Recap

* SEP-990 lets the enterprise identity provider, not the end user, decide which MCP servers a client may reach. The IdP signs that decision into an **ID-JAG**.
* Obtaining the ID-JAG is an RFC 8693 token exchange against *your IdP*, and the SDK does not make it. Presenting it to the MCP authorization server is the RFC 7523 `jwt-bearer` grant, and the SDK does both sides of that.
* `IdentityAssertionOAuthProvider` is another `httpx.Auth`: a pre-registered confidential client, a pinned `issuer`, and one `assertion_provider(audience, resource)` callback. No browser, no registration, no refresh token.
* The authorization server is never discovered from the resource server. Configure `issuer` to exactly the string its metadata document serves; the comparison is character for character.
* Server side, `identity_assertion_enabled=True` plus `exchange_identity_assertion`. The SDK authenticates the client and gates the grant; validating the ID-JAG is entirely yours, and the issued token is bound to the ID-JAG's `resource`, not the request's.

The one party this page never touched is the MCP server. What it does with the token you just minted, it was already doing in **Authorization**.
