# URI templates and path safety

This is the reference for the URI-template syntax that
[`@mcp.resource`](resources.md) accepts, and for the
path-safety policy the SDK applies to extracted values. For an
introduction to what resources are and when to use them, start with
**[Resources](resources.md)**; this page assumes you're already comfortable declaring a
resource and want the full operator set, the security knobs, or the
low-level wiring.

The template syntax is [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
The SDK supports a subset chosen for matching incoming `resources/read`
URIs, plus a security layer that rejects values that would resolve
outside the directory you intend to serve. For the protocol-level
details (message formats, lifecycle, pagination) see the
[MCP resources specification](https://modelcontextprotocol.io/specification/latest/server/resources).

## The full operator set

The plain placeholder, `{user_id}`, is the one **[Resources](resources.md)** introduces. There are four more
operator forms; here they are on one server so you can see them next to
each other:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Each highlighted decorator is a different way of carving up the URI.
The sections below walk them top to bottom.

### Simple expansion: `{name}`

`books://{isbn}` is the plain, everyday form. The placeholder maps to
the `isbn` parameter, so a client reading `books://978-0441172719` calls
`get_book("978-0441172719")`.

A plain `{name}` stops at the first `/`. `books://978/extra` does not
match because the slash after `978` ends the capture and `/extra` is
left over.

### Type conversion

Extracted values arrive as strings, but you can declare a more specific
type and the SDK will convert. `orders://{order_id}` lands in a function
whose parameter is `order_id: int`, so reading `orders://12345` calls
`get_order(12345)`, not `get_order("12345")`. The handler does
arithmetic on it (`order_id + 1`) without a cast.

### Multi-segment paths: `{+name}`

To capture a value that contains slashes, use `{+name}`. With
`manuals://{+path}`:

* `manuals://returns.md` gives `path = "returns.md"`
* `manuals://printing/setup.md` gives `path = "printing/setup.md"`

Reach for `{+name}` whenever the value is hierarchical: filesystem
paths, nested object keys, URL paths you're proxying.

### Query parameters: `{?a,b,c}`

`reviews://{isbn}{?limit,sort}` puts `limit` and `sort` after the `?`.
The path identifies *which* book; the query tunes *how* you read it.

Query params are matched leniently: order doesn't matter, extras are
ignored, and omitted params fall through to your function defaults. So
`reviews://978-0441172719` uses `limit=10, sort="newest"`, and
`reviews://978-0441172719?sort=top` overrides only `sort`.

### Path segments as a list: `{/name*}`

If you want each path segment as a separate list item rather than one
string with slashes, use `{/name*}`. With `shelves://browse{/path*}`, a
client reading `shelves://browse/fiction/sci-fi` calls
`browse_shelf(["fiction", "sci-fi"])`.

### Template reference

The most common patterns:

| Pattern      | Example input         | You get                 |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *no match* (stops at `/`) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### What the parser rejects

A few template shapes are caught up front rather than failing on the
first request. `@mcp.resource` parses the template when the decorator
runs, so none of these ever reach a running server.

`UriTemplate.parse()` raises `InvalidUriTemplate` for:

* **Two variables with nothing between them.** `manuals://{+path}{ext}`
  is rejected: matching can't tell where `path` ends and `ext` begins.
  Put a literal between them (`manuals://{+path}/{ext}`), or use an
  operator that supplies its own delimiter. `manuals://{+path}{.ext}`
  is accepted because `{.ext}` contributes the `.` itself.
* **More than one multi-segment variable.** At most one of `{+var}`,
  `{#var}`, or an exploded variable (`{/var*}`, `{.var*}`, `{;var*}`)
  per template. Two are inherently ambiguous: there is no principled
  way to decide which one absorbs an extra segment.
* **The usual syntax errors**: an unclosed brace, a variable name used
  twice, or an RFC 6570 feature the SDK doesn't support, such as the
  `{var:3}` prefix modifier or the `{?vars*}` query explode.

On top of that, `@mcp.resource` raises `ValueError` when a handler
parameter is bound to a query variable in the template's trailing
`{?...}`/`{&...}` run but has no Python default. Those variables are
matched leniently (a client may leave any of them out), so a parameter
without a default would only surface as an opaque internal error on the
first request that omits it. `reviews://{isbn}{?limit,sort}` in the
server above is the well-formed version: `limit` and `sort` both carry
defaults.

## Security

Template parameters come from the client. If they flow into filesystem
or database operations unchecked, values like `../../etc/passwd` can
resolve outside the directory you intended to serve.

### What the SDK checks by default

Before your handler runs, the SDK rejects any parameter that:

* would escape its starting directory via `..` components
* looks like an absolute path (`/etc/passwd`, `C:\Windows`) or a
  Windows drive-relative one (`C:foo`). A drive-relative value and a
  namespaced identifier like `x:y` are indistinguishable as strings,
  so any single-letter-plus-colon value is rejected by default;
  exempt the parameter if it legitimately receives such values
* contains a null byte (`\x00`)

The `..` check is component-based, not a substring scan. Values like
`v1.0..v2.0` or `HEAD~3..HEAD` pass because `..` is not a standalone
path segment there.

These checks apply to the decoded value, so they catch traversal
regardless of how it was encoded in the URI (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc`, `%00` all get caught).

!!! check
    Read `manuals://../etc/passwd` from the server above and the request
    is rejected outright: template matching stops at the first failure,
    so no later (potentially more permissive) template is tried as a
    fallback. The client sees the same `-32602` "Unknown resource" error
    it would for a URI that matches no template at all, and
    `read_manual` never runs.

### Filesystem handlers: use safe_join

The built-in checks stop the common cases but can't know your sandbox
boundary. For filesystem access, use `safe_join` to resolve the path
and verify it stays inside your base directory:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` catches symlink escapes, `..` sequences, and absolute-path
tricks that a simple string check would miss. If the resolved path
escapes `DOCS_ROOT`, it raises `PathEscapeError`, which surfaces to the
client as a `ResourceError`.

### When the defaults get in the way

Sometimes the checks block legitimate values. A catalog-import tool
might intentionally receive an absolute path, or a parameter might be a
relative reference like `../sibling` that your handler interprets
safely without touching the filesystem. Exempt that parameter, or relax
the policy for the whole server:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* `security=ResourceSecurity(exempt_params={"source"})` on the decorator
  skips the checks for that one parameter on that one resource. The
  rest of the server keeps the default policy.
* `resource_security=` on the `MCPServer` constructor sets the default
  for every resource. Here `relaxed` turns off the `..` check entirely.

The configurable checks:

| Setting                 | Default | What it does                        |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Rejects `..` sequences that escape the starting directory |
| `reject_absolute_paths` | `True`  | Rejects `/foo`, `C:\foo`, UNC paths, and drive-relative `C:foo` (also catches `x:y`) |
| `reject_null_bytes`     | `True`  | Rejects values containing `\x00`    |
| `exempt_params`         | empty   | Parameter names to skip checks for  |

These checks are a heuristic pre-filter; for filesystem access,
`safe_join` remains the containment boundary.

!!! tip
    If your handler can't fulfil the request (the file doesn't exist,
    the id is unknown), raise an exception. The SDK turns it into an
    error response. See **[Handling errors](handling-errors.md)** for the difference between a
    protocol error and a tool error.

## Resources on the low-level Server

If you're building on the low-level `Server` (see **[The low-level
Server](../advanced/low-level-server.md)**), you register handlers for the `resources/list` and
`resources/read` protocol methods directly. There's no decorator; you
return the protocol types yourself.

### Static resources

For fixed URIs, keep a registry and dispatch on exact match:

```python title="server.py" hl_lines="18 22 28"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

The list handler tells clients what's available; the read handler
serves the content. Check your registry first, fall through to
templates (below) if you have any, then raise for anything else.

### Templates

The template engine `MCPServer` uses lives in `mcp.shared.uri_template`
and works on its own. You get the same parsing and matching; you wire
up the routing and security policy yourself.

```python title="server.py" hl_lines="14-17 23-26 30 34 46"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

Three things are happening in the highlighted lines:

* **Parse once, match per request.** `UriTemplate.parse()` builds the
  template; `template.match(uri)` returns the extracted variables as a
  `dict`, or `None` if the URI doesn't fit. URL decoding happens inside
  `match()`; the decoded values are returned as-is without path-safety
  validation. Values come out as strings: convert them yourself
  (`int(matched["id"])`, `Path(matched["path"])`).
* **Apply the safety checks yourself.** The `..` and absolute-path
  checks `MCPServer` runs by default live in `mcp.shared.path_security`.
  `read_manual_safely` calls them before touching `MANUALS`. If a
  parameter isn't a filesystem path (an ISBN, a search query), skip the
  checks for that value: you control the policy per handler rather than
  through a config object.
* **List the templates from the same source.** Clients discover
  templates through `resources/templates/list`. `str(template)` gives
  back the original template string, so the listing and the matcher
  share one source of truth.

## Recap

* `{name}` matches one segment; `{+name}` keeps the slashes; `{?a,b}`
  pulls from the query string; `{/name*}` splits segments into a list.
* Two variables with nothing between them, or a second multi-segment
  variable, are rejected at parse time. A parameter bound to a trailing
  `{?...}`/`{&...}` query variable must declare a Python default.
* Annotate the parameter (`order_id: int`) and the SDK converts.
* The default security policy rejects `..`, absolute paths, and null
  bytes before your handler runs; override per resource with
  `security=ResourceSecurity(...)` or server-wide with
  `resource_security=`.
* For filesystem access, `safe_join` is the containment boundary.
* On the low-level `Server`, parse with `UriTemplate.parse()`, match
  with `.match()`, and apply `mcp.shared.path_security` yourself.
