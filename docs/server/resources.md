# Resources

Resources give clients read-only access to your data. Think of them as
the files, records, and reference material an LLM might need as context:
a config file, a database schema, the contents of a document, yesterday's
log output.

Resources are different from tools. A tool is something the model
*calls* to make something happen: send an email, run a query, write a
file. A resource is something the application *reads* to understand the
world. Reading a resource should not change state or kick off expensive
work. If it does either, you probably want a tool.

For the protocol-level details (message formats, lifecycle, pagination),
see the [MCP resources specification](https://modelcontextprotocol.io/specification/latest/server/resources).

## A static resource

The simplest case is a fixed URI that returns the same kind of content
every time.

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("docs-server")


@mcp.resource("config://features")
def feature_flags() -> str:
    return '{"beta_search": true, "new_editor": false}'
```

When a client reads `config://features`, your function runs and the
return value is sent back. Return `str` for text, `bytes` for binary
data, or anything JSON-serializable.

The URI scheme (`config://` here) is up to you. The protocol reserves
`file://` and `https://` for their usual meanings, but custom schemes
like `config://`, `db://`, or `notes://` are encouraged. They make the
URI self-describing.

## Resource templates

Most interesting data is parameterized. You don't want to register a
separate resource for every user, every file, every database row.
Instead, register a template with placeholders:

```python
@mcp.resource("tickets://{ticket_id}")
def get_ticket(ticket_id: str) -> dict[str, str]:
    ticket = helpdesk.find(ticket_id)
    return {"id": ticket_id, "subject": ticket.subject, "status": ticket.status}
```

The `{ticket_id}` in the URI maps to the `ticket_id` parameter in your
function. A client reading `tickets://TKT-1042` calls
`get_ticket("TKT-1042")`. Reading `tickets://TKT-2001` calls
`get_ticket("TKT-2001")`. One template, unlimited resources.

### Parameter types

Extracted values arrive as strings, but you can declare a more specific
type and the SDK will convert:

```python
@mcp.resource("orders://{order_id}")
def get_order(order_id: int) -> dict[str, Any]:
    # "12345" from the URI becomes the int 12345
    return db.orders.get(order_id)
```

### Multi-segment paths

A plain `{name}` stops at the first slash. If your template is
`files://{name}`, a client reading `files://readme.txt` matches fine,
but `files://guides/intro.md` does not: the slash after `guides` ends
the match, and `intro.md` is left over.

To capture the whole path including slashes, use `{+name}`:

```python
@mcp.resource("files://{+path}")
def read_file(path: str) -> str:
    # files://readme.txt        gives path = "readme.txt"
    # files://guides/intro.md   gives path = "guides/intro.md"
    ...
```

Reach for `{+name}` whenever the value is hierarchical: filesystem
paths, nested object keys, URL paths you're proxying.

### Query parameters

Say you want clients to read `logs://api` for recent logs, but also
`logs://api?since=15m&level=error` when they need to narrow it down.
The `?since=15m&level=error` part is optional configuration, and you
don't want a separate template for every combination.

Declare these as query parameters with `{?name}`, or list several at
once with `{?a,b,c}`:

```python
@mcp.resource("logs://{service}{?since,level}")
def tail_logs(service: str, since: str = "1h", level: str = "info") -> str:
    return log_store.query(service, since=since, min_level=level)
```

The path identifies *which* resource; the query tunes *how* you read
it.

Query params are matched leniently: order doesn't matter, extras are
ignored, and omitted params fall through to your function defaults.

### Path segments as a list

If you want each path segment as a separate list item rather than one
string with slashes, use `{/name*}`:

```python
@mcp.resource("tree://nodes{/path*}")
def walk_tree(path: list[str]) -> dict[str, Any]:
    # tree://nodes/a/b/c gives path = ["a", "b", "c"]
    node = root
    for segment in path:
        node = node.children[segment]
    return node.to_dict()
```

### Template reference

The template syntax follows [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
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

## Security

Template parameters come from the client. If they flow into filesystem
or database operations, a hostile client can try path traversal
(`../../etc/passwd`) or injection attacks.

### What the SDK checks by default

Before your handler runs, the SDK rejects any parameter that:

- would escape its starting directory via `..` components
- looks like an absolute path (`/etc/passwd`, `C:\Windows`)

The `..` check is component-based, not a substring scan. Values like
`v1.0..v2.0` or `HEAD~3..HEAD` pass because `..` is not a standalone
path segment there.

These checks apply to the decoded value, so they catch traversal
regardless of how it was encoded in the URI (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc` all get caught).

A request that trips these checks is treated as a non-match: the SDK
raises `ResourceError("Unknown resource: {uri}")`, which the client
receives as a JSON-RPC error. Your handler never sees the bad input.

### Filesystem handlers: use safe_join

The built-in checks stop obvious attacks but can't know your sandbox
boundary. For filesystem access, use `safe_join` to resolve the path
and verify it stays inside your base directory:

```python
from mcp.shared.path_security import safe_join

DOCS_ROOT = "/srv/app/docs"


@mcp.resource("files://{+path}")
def read_file(path: str) -> str:
    full_path = safe_join(DOCS_ROOT, path)
    return full_path.read_text()
```

`safe_join` catches symlink escapes, `..` sequences, and absolute-path
tricks that a simple string check would miss. If the resolved path
escapes the base, it raises `PathEscapeError`, which surfaces to the
client as a `ResourceError`.

### When the defaults get in the way

Sometimes the checks block legitimate values. An external-tool wrapper
might intentionally receive an absolute path, or a parameter might be a
relative reference like `../sibling` that your handler interprets
safely without touching the filesystem. Exempt that parameter:

```python
from mcp.server.mcpserver import ResourceSecurity


@mcp.resource(
    "inspect://file/{+target}",
    security=ResourceSecurity(exempt_params={"target"}),
)
def inspect_file(target: str) -> str:
    # target might be "/usr/bin/python3"; this handler is trusted
    return describe_binary(target)
```

Or relax the policy for the whole server:

```python
mcp = MCPServer(
    resource_security=ResourceSecurity(reject_path_traversal=False),
)
```

The configurable checks:

| Setting                 | Default | What it does                        |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Rejects `..` sequences that escape the starting directory |
| `reject_absolute_paths` | `True`  | Rejects `/foo`, `C:\foo`, UNC paths |
| `reject_null_bytes`     | `True`  | Rejects values containing `\x00`    |
| `exempt_params`         | empty   | Parameter names to skip checks for  |

These checks are a heuristic pre-filter; for filesystem access,
`safe_join` remains the containment boundary.

## Errors

If your handler can't fulfil the request, raise an exception. The SDK
turns it into an error response:

```python
@mcp.resource("articles://{article_id}")
def get_article(article_id: str) -> str:
    article = db.articles.find(article_id)
    if article is None:
        raise ValueError(f"No article with id {article_id}")
    return article.content
```

## Resources on the low-level server

If you're building on the low-level `Server`, you register handlers for
the `resources/list` and `resources/read` protocol methods directly.
There's no decorator; you return the protocol types yourself.

### Static resources

For fixed URIs, keep a registry and dispatch on exact match:

```python
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import (
    ListResourcesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextResourceContents,
)
from mcp.server.context import ServerRequestContext

RESOURCES = {
    "config://features": lambda: '{"beta_search": true}',
    "status://health": lambda: check_health(),
}


async def on_list_resources(
    ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
) -> ListResourcesResult:
    return ListResourcesResult(
        resources=[Resource(name=uri, uri=uri) for uri in RESOURCES]
    )


async def on_read_resource(
    ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
) -> ReadResourceResult:
    if (producer := RESOURCES.get(params.uri)) is not None:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=params.uri, text=producer())]
        )
    raise ValueError(f"Unknown resource: {params.uri}")


server = Server(
    "my-server",
    on_list_resources=on_list_resources,
    on_read_resource=on_read_resource,
)
```

The list handler tells clients what's available; the read handler
serves the content. Check your registry first, fall through to
templates (below) if you have any, then raise for anything else.

### Templates

The template engine `MCPServer` uses lives in `mcp.shared.uri_template`
and works on its own. You get the same parsing and matching; you wire
up the routing and security policy yourself.

#### Matching requests

Parse your templates once, then match incoming URIs against them in
your read handler:

```python
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.uri_template import UriTemplate
from mcp.types import ReadResourceRequestParams, ReadResourceResult, TextResourceContents

TEMPLATES = {
    "files": UriTemplate.parse("files://{+path}"),
    "row": UriTemplate.parse("db://{table}/{id}"),
}


async def on_read_resource(
    ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
) -> ReadResourceResult:
    if (vars := TEMPLATES["files"].match(params.uri)) is not None:
        content = read_file_safely(vars["path"])
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=content)])

    if (vars := TEMPLATES["row"].match(params.uri)) is not None:
        row = db.get(vars["table"], int(vars["id"]))
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=row.to_json())])

    raise ValueError(f"Unknown resource: {params.uri}")


server = Server("my-server", on_read_resource=on_read_resource)
```

`UriTemplate.match()` returns the extracted variables or `None`. URL
decoding happens inside `match()`; the decoded values are returned
as-is without path-safety validation.

Values come out as strings. Convert them yourself: `int(vars["id"])`,
`Path(vars["path"])`, whatever your handler needs.

#### Applying security checks

The path traversal and absolute-path checks that `MCPServer` runs by
default are in `mcp.shared.path_security`. Call them before using an
extracted value:

```python
from mcp.shared.path_security import contains_path_traversal, is_absolute_path, safe_join

DOCS_ROOT = "/srv/app/docs"


def read_file_safely(path: str) -> str:
    if contains_path_traversal(path) or is_absolute_path(path):
        raise ValueError("rejected")
    return safe_join(DOCS_ROOT, path).read_text()
```

If a parameter isn't a filesystem path (say, a git ref or a search
query), skip the checks for that value. You control the policy per
handler rather than through a config object.

#### Listing templates

Clients discover templates through `resources/templates/list`. Return
the protocol `ResourceTemplate` type, using the same template strings
you parsed above:

```python
from typing import Any

from mcp.types import ListResourceTemplatesResult, PaginatedRequestParams, ResourceTemplate


async def on_list_resource_templates(
    ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
) -> ListResourceTemplatesResult:
    return ListResourceTemplatesResult(
        resource_templates=[
            ResourceTemplate(name="files", uri_template=str(TEMPLATES["files"])),
            ResourceTemplate(name="row", uri_template=str(TEMPLATES["row"])),
        ]
    )


server = Server(
    "my-server",
    on_read_resource=on_read_resource,
    on_list_resource_templates=on_list_resource_templates,
)
```

`str(template)` gives back the original template string, so your list
handler and your matching logic can share one source of truth.
