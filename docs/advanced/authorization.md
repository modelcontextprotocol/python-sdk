# Authorization

Over Streamable HTTP your MCP server is an ordinary web service, and you protect it the way you protect any web service: with OAuth 2.1 bearer tokens.

In OAuth terms, your server is a **resource server**. It never signs anyone in and it never issues a token. It does one thing: look at the `Authorization` header on each request and decide whether the token in it is good.

## The three parties

* The **authorization server** signs people in and issues access tokens. You don't write this. It's your identity provider (Auth0, Keycloak, Entra, your own).
* The **resource server** is your MCP server. It verifies the token on every request.
* The **client** discovers which authorization server you trust, gets a token from it, and sends it back to you as `Authorization: Bearer <token>`.

That's the whole triangle. Everything on this page is the middle bullet.

## A token verifier

The SDK has no opinion about what a valid token looks like. You tell it, by implementing **`TokenVerifier`**:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` is a protocol with one async method. `verify_token` gets the raw token from the `Authorization` header and returns an **`AccessToken`** if it's valid, `None` if it isn't. There is nothing else to implement.
* This one looks the token up in a table. A real one verifies a JWT signature or calls the authorization server's token-introspection endpoint. That code is yours; the SDK only calls it.
* `token_verifier=` and `auth=` always travel together. Pass one without the other and `MCPServer(...)` raises a `ValueError` before it ever serves a request.

`AuthSettings` is the public face of your resource server:

* `issuer_url`: the authorization server that issues your tokens.
* `resource_server_url`: the public URL of this MCP endpoint. It names *which* resource a token is for, and it's where the discovery document lives.
* `required_scopes`: every token must carry all of them.

!!! tip
    `examples/servers/simple-auth/` in the SDK repository has an `IntrospectionTokenVerifier` that calls
    a real authorization server's [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) endpoint. It's the shape most production verifiers take.

## What you get over HTTP

Authorization lives in HTTP headers, so it exists only on the HTTP transports. Run it on the one you deploy: `mcp.run(transport="streamable-http")` puts it on `http://127.0.0.1:8000/mcp`, and **[Running your server](../run/index.md)** has the rest. The app now has two routes:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

You registered one tool. The second route is the SDK's.

### Discovery

`GET` that well-known path and you get **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata**, built straight from your `AuthSettings`:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

This document is how a client that has never heard of your server finds its way in: it reads `authorization_servers` and goes there for a token. You wrote none of it.

!!! check
    Call `/mcp` with no token (or with one your verifier returned `None` for) and the request is
    stopped at the door:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    Nothing was parsed and no tool ran. And that `resource_metadata` pointer in `WWW-Authenticate` is
    what makes discovery automatic: 401 -> metadata document -> authorization server -> token -> retry.

!!! warning
    None of this protects `stdio`. A pipe has no `Authorization` header, so `token_verifier` is never
    consulted there. A `stdio` server's security boundary is the process that launched it. The same
    goes for the in-memory `Client(mcp)` you use in tests: it connects straight to the server object
    and skips the HTTP layer, authorization included.

## The caller's identity

Inside any handler, **`get_access_token()`** is the `AccessToken` your verifier returned for the current request:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* It works in tools, resources, and prompts, and there is nothing to pass around: the auth middleware stores it in a context variable per request.
* You get back the **same object your verifier built**: `client_id`, `scopes`, `subject`, `expires_at`, and any extra `claims` you attached. That's the hook for per-tool rules: read the scopes and refuse.
* Outside an authenticated HTTP request it returns `None`. In-memory and over `stdio` it is always `None`.

Call `whoami` with `Authorization: Bearer alice-token` and the model reads:

```text
alice (scopes: notes:read)
```

## The half the SDK doesn't do

The SDK gives you the resource-server half: verify, advertise, refuse. It does not give you a login page, a consent screen, or a token.

To watch all three parties move, run `examples/servers/simple-auth/` from the SDK repository (a small authorization server and a resource server set up exactly like this page) and then point `examples/clients/simple-auth-client/` at it for the full discovery-and-token dance.

!!! info
    There is a second constructor argument, `auth_server_provider=`, that embeds a full authorization
    server inside your MCP server. It predates the AS/RS separation that the MCP authorization spec
    is built around. New servers should not reach for it.

An authorization server can also accept an enterprise identity provider's signed assertion in place of a user clicking through a consent screen, and the SDK supports both sides of that exchange. The grant, and the client that presents it, is **[Identity assertion](identity-assertion.md)**.

## Recap

* Over Streamable HTTP your server is an OAuth 2.1 **resource server**: it verifies tokens, it never issues them.
* `TokenVerifier` is the whole integration surface: one async method, token in, `AccessToken | None` out.
* `token_verifier=` and `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` always travel together.
* The SDK publishes [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata at `/.well-known/oauth-protected-resource/...` and answers unauthenticated requests with a 401 whose `WWW-Authenticate` header points at it. That is the entire discovery story.
* `get_access_token()` in any handler is who's calling.
* Authorization is an HTTP concern. `stdio` and the in-memory client never see it.

The other side of the handshake, a client that discovers your authorization server and fetches the token for you, is **[OAuth clients](oauth-clients.md)**.
