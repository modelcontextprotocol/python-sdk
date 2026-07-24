# Server Cards

!!! warning "Experimental"
    Server Cards are an experimental MCP extension tracking
    [SEP-2127](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127).
    Everything on this page lives under `experimental` modules and may change or be
    removed in any release without a deprecation cycle.

A **Server Card** is a static JSON document that describes a single remote MCP server
well enough for a client to discover it and connect, before any protocol exchange:
identity (`name`, `version`, `description`, `title`, `icons`, `repository`,
`websiteUrl`), the transport endpoints (`remotes[]` with URL templates, header inputs
and supported protocol versions), and namespaced `_meta` for anything else. It is served
as `application/mcp-server-card+json`.

A card deliberately omits two things. Tools, resources and prompts stay behind the
runtime `list` operations. Local install metadata (packages, registries, arguments,
environment) belongs to the MCP Registry's `server.json`. If you need install hints,
put them in `_meta`.

## Serving a card

The spec reserves `GET <your streamable HTTP URL>/server-card` as the default location,
and domain-level discovery reads an **AI Catalog** at `/.well-known/ai-catalog.json`.
`mount_discovery` sets up both on a single-domain deployment:

```python title="serve_card.py" hl_lines="12 19"
--8<-- "docs_src/server_cards/tutorial001.py"
```

`build_server_card` derives `title`, `description`, `version`, `websiteUrl` and `icons`
from the server object, so the card stays consistent with what `serverInfo` reports at
runtime. Explicit keyword arguments override the derived values. The namespaced card
`name` and the public `remotes` URLs are yours to supply, since the server object cannot
know them.

With the app above, `GET /mcp/server-card` and `GET /.well-known/ai-catalog.json` both
answer with the spec's required headers: the correct `Content-Type`, the CORS headers
the spec mandates on card endpoints, a `Cache-Control: public, max-age=3600` default,
and a strong `ETag` that turns a matching `If-None-Match` into an empty `304`.

The card routes are appended to the app after `streamable_http_app()` builds it. Mount
them outside any auth middleware. Discovery is unauthenticated by design, and a card or
catalog must never contain credentials, internal topology or private endpoints.

`public_url` is the externally visible base URL at which the app's root is served,
typically just the origin. Only include a path prefix when a reverse proxy really serves
the app under it, since the catalog entry advertises `public_url` plus the card path.

If you need only one of the two endpoints, or different paths, use the smaller pieces:
`create_server_card_routes` / `mount_server_card` for the card and
`create_ai_catalog_routes` / `mount_ai_catalog` for the catalog. For fully custom
hosting (say a FastAPI route), `discovery_response` is the compliance chokepoint that
produces a correct response from a request and the document bytes.

## Publishing on your brand domain

The catalog belongs on the domain users associate with your service, which is often
different from the API host (think `github.com` versus `api.githubcopilot.com`). In that
case skip `mount_discovery` and build the entry yourself with `server_card_entry`, then
publish it in the catalog your brand domain serves. Entries can point at the hosted card
by URL or inline the whole card as `data`.

A card is just JSON, so static publishing needs no server at all:

```python title="publish_static.py"
--8<-- "docs_src/server_cards/tutorial004.py"
```

Upload the result to your CDN and reference it from your catalog.

## Discovering and connecting

`discover_server_cards` is one probe: it fetches the well-known catalog of the URL's
origin, follows Server Card entries (by URL or inline `data`) and nested catalogs, and
returns every card it found. It never runs implicitly. Your host decides when to probe.

```python title="discover_and_connect.py" hl_lines="10 16"
--8<-- "docs_src/server_cards/tutorial002.py"
```

`resolve_remote` substitutes the card's `{curly_brace}` variables using declared
defaults and your values, and raises a `ValueError` naming every missing required input,
so you can prompt for all of them at once. `Remote.required_variables` lists them up
front.

The probe collects per-entry problems in `DiscoveryResult.failures` instead of raising,
so one hostile or broken entry never hides the rest. Each `CardListing` carries the
listing chain for your consent UI: `listing_domain` is where the catalog listed the
card, `hosting_domain` is where the card itself lives, and they legitimately differ.

For local development the hardened defaults get in the way (plain http and loopback
targets are blocked). Opt in explicitly with
`DiscoveryPolicy(allow_private_addresses=True)`.

## Caching and revalidation

Clients should honor `Cache-Control` and avoid polling. The SDK deliberately ships no
cache storage. Instead, the stateless request/parse pairs let your host revalidate with
its own store:

```python title="revalidate.py" hl_lines="16 18"
--8<-- "docs_src/server_cards/tutorial003.py"
```

Store the `ETag` alongside the card and send it back as `If-None-Match`. An unchanged
card costs a 304 and no body.

## Security model

Cards are unverified, advisory input. The rules that keep discovery safe:

- **Runtime wins.** A card's claims should match the live server, and
  `reconcile_server_card` reports any drift, but clients must never treat card contents
  as authoritative for security or access-control decisions.
- **De-duplicate on endpoints.** `name` and the catalog `identifier` are self-asserted
  and spoofable. `ServerCard.endpoint_urls()` gives you the dedup key: the card's actual
  `remotes[]` URLs.
- **Never auto-install.** Consent, its persistence ("not now", "this session",
  "always"), decline memory and enterprise allowlists are host application policy. The
  SDK exposes the data and stays out of the decision.
- **Hardened fetching.** Every fetch, redirect hop and nested catalog follow is checked
  under `DiscoveryPolicy`: https only (plain http needs `allow_private_addresses=True`),
  no userinfo in URLs, an SSRF guard that rejects private, loopback, link-local and
  metadata addresses (checked again after DNS resolution), bounded redirects, response
  size and entry count caps, a whole-probe entry budget with already-visited catalogs
  never refetched, and no cookies or ambient credentials. If you pass your own
  `http_client`, keep it credential-free. The guard resolves DNS before the request
  while the client re-resolves on connect, so a DNS rebinding race remains possible
  between the two.
