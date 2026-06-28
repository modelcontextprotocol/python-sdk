# MCP Apps

An **MCP App** is a tool with a face: alongside its data, the tool points at an HTML
document the host renders as an interactive surface.

Two parts, always two parts:

1. **A tool** that does the work and returns data, like any other tool.
2. **A `ui://` resource** containing the HTML the host shows for it.

The tool carries a `_meta.ui.resourceUri` reference to the resource. The host fetches
it with `resources/read`, renders it in a **sandboxed iframe**, and pushes the tool's
result into that iframe via `postMessage`. Your server never sends or receives any
`ui/*` messages: that traffic is between the host and the iframe. You serve a tool
and an HTML document; the host does the theater.

The SDK ships this as the built-in `Apps` extension (`io.modelcontextprotocol/ui`).
If [Extensions](extensions.md) are new to you, skim that page first. One minute,
then come back.

## A clock with a face

```python title="server.py" hl_lines="17 20 23-24 28 30"
--8<-- "docs_src/apps/tutorial001.py"
```

Four moves:

* `Apps()`: one instance holds your UI-bound tools and their resources.
* `@apps.tool(resource_uri="ui://clock/app.html")`: a regular tool, plus the
  `_meta.ui.resourceUri` stamp. Everything `@mcp.tool()` accepts (name, title,
  description, ...) passes through.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: the matching
  resource, served as `text/html;profile=mcp-app`. That exact MIME type is what
  tells a host "this is an app, render it".
* `MCPServer("clock", extensions=[apps])`: opt in. The server now advertises
  `io.modelcontextprotocol/ui` under `capabilities.extensions`.

The HTML itself listens for the host's `postMessage` and shows the result. For real
apps, use the official [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps)
browser SDK inside your HTML. It gives you `ontoolresult`, `callServerTool`,
`getHostContext`, and `onhostcontextchanged` instead of raw message events.

## Graceful degradation

Not every client renders apps. The spec is blunt about what that means for you:

> Tools **MUST** return a meaningful `content` array even when UI is available.

The model reads `content`; the iframe is for humans. A UI-capable host still feeds
the text result to the model, and a text-only client gets *only* that. So the
canonical pattern is one tool, two answers:

```python
@apps.tool(resource_uri="ui://clock/app.html")
def get_time(ctx: Context) -> str:
    now = current_time()
    if not client_supports_apps(ctx):
        return f"The time is {now}."   # a sentence for humans without the UI
    return now                          # raw data the app renders
```

`client_supports_apps(ctx)` is `True` only when the client declared the
`io.modelcontextprotocol/ui` extension **and** listed `text/html;profile=mcp-app`
in its `mimeTypes` settings. The field is required, so a client that omits it
does not count.

!!! warning
    Never return a placeholder like `"[Rendered UI]"` as the only content. If the
    fallback text is useless, the tool is useless to every text-only client and to
    the model itself. Write the sentence.

A client declares support like any extension capability:

```python
from mcp import Client
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

async with Client(target, extensions={EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}) as client:
    ...
```

## Locking the iframe down

The resource side carries the security metadata: what the iframe may load, which
browser permissions it wants, how it would like to be framed:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` and `permissions` are **requests to the host**, not server behaviour. The host
builds the iframe's Content-Security-Policy and Permissions-Policy from them, and it
may refuse. Feature-detect in your JS rather than assuming a grant.

`ResourceCsp`, field by field (Python name, wire key, what the host does with it):

| Python | Wire (`_meta.ui.csp`) | Controls |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: where `fetch`/XHR may go |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: static assets |
| `frame_domains` | `frameDomains` | `frame-src`: nested iframes |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: what `<base>` may point at |

`ResourcePermissions`: each field requests a browser permission for the iframe.

| Python | Wire (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP and permissions live on the **resource**, never on the tool. The spec's tool
    metadata has no slot for them, and hosts ignore them there. The SDK makes the
    mistake unrepresentable: `@apps.tool()` simply has no `csp` parameter.

### Visibility

`visibility=["app"]` on a tool says "this exists for the iframe, not the model":

* `"model"`: the model may call it.
* `"app"`: the iframe may call it (via `callServerTool`).
* Omitted: both, which is the default.

Filtering is the **host's** job. Your server lists app-only tools in `tools/list`
like any other; the host hides them from the model. Don't filter server-side.

## The rules the SDK enforces

All of these fail at startup, not in production:

* A `resource_uri` or resource URI that isn't `ui://...` is a `ValueError` at
  decoration/registration time.
* A tool bound to a URI with **no matching registered resource** is a `ValueError`
  when `MCPServer(extensions=[apps])` consumes the extension. A tool advertising
  HTML that 404s on `resources/read` is a misconfiguration, so it refuses to
  construct.
* `meta={"ui": ...}` on `@apps.tool()` is a `ValueError`. The decorator owns
  `_meta["ui"]`; say it with `resource_uri=` and `visibility=`. Other `meta=` keys
  merge fine alongside.

Neither the TypeScript ext-apps SDK nor FastMCP catches any of these today; we'd
rather you find out before a host does.

## Beyond inline HTML

`add_html_resource` covers the common case: a string of HTML. For anything else,
HTML on disk or generated content, build the resource yourself and hand it over:

```python
from mcp.server.mcpserver.resources import FileResource

apps.add_resource(FileResource(uri="ui://report/app.html", name="report", path=html_path))
```

`add_resource` fills in the `text/html;profile=mcp-app` MIME type when the resource
doesn't set one explicitly, and rejects an explicit mismatch: a `ui://` resource
under any other MIME type is one no host will render.

!!! tip
    Targeting a pre-GA host that still reads the deprecated flat
    `_meta["ui/resourceUri"]` key? Merge it yourself:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    The nested `ui` object is the spec shape; the flat key is on its way out.

## See it run

The `apps` story in `examples/stories/` is this page as a runnable pair: a server
with a UI-bound clock tool and a client that negotiates Apps, reads the tool's
`_meta.ui.resourceUri`, fetches the HTML, and calls the tool.

```bash
uv run python -m stories.apps.client
```
