# Installation

The Python SDK is on PyPI as [`mcp`](https://pypi.org/project/mcp/). It requires **Python 3.10+**.

These docs describe **v2**, the current stable release line:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Coming from v1?"
    v2 is a major version with breaking changes; the **[Migration Guide](../migration.md)**
    covers every one. If your *package* depends on `mcp` and isn't ready to migrate, keep a
    `<2` upper bound (for example `mcp>=1.28,<2`) so an unpinned resolve stays on the 1.x line.

## Client-only installation

```bash
uv add mcp-client
```

```python
import anyio

from mcp_client import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        tools = await client.list_tools()
        for tool in tools.tools:
            print(tool.name)


anyio.run(main)
```

Run this example against an MCP server listening at `http://localhost:8000/mcp`.

Use `mcp-client` when you only connect to servers. It includes the client transports,
OAuth support, and shared protocol machinery without installing Starlette, Uvicorn,
`sse-starlette`, or `python-multipart`. Import client APIs from `mcp_client`, OAuth
support from `mcp_client.client.auth`, and protocol types from `mcp_types`.

Install `mcp` if you also build servers, use the CLI, or pass a server instance to
`Client(server)` for in-process testing. Existing `mcp` imports keep working and
refer to the same client implementation. All three distributions release together;
`mcp` requires its exact `mcp-client` version, which requires its exact `mcp-types` version.

## What gets installed

You don't need to know any of this to use the SDK, but if you're wondering what each dependency is for:

* `mcp-client`: the client API, transports, OAuth support, and shared protocol machinery, versioned in lockstep with the SDK.
* `mcp-types`: every protocol type (requests, results, content blocks) as its own package, versioned in lockstep with the SDK. Code that depends on `mcp` imports it through the `mcp.types` alias (every `from mcp.types import ...` in these docs); import `mcp_types` directly only in a project that installs `mcp-types` without the SDK.
* [`anyio`](https://anyio.readthedocs.io/): the async runtime. The whole SDK is written against anyio, so it runs on either `asyncio` or `trio`.
* [`pydantic`](https://docs.pydantic.dev/): what every `mcp.types` model is built on, plus all schema generation and validation.
* [`httpx2`](https://pypi.org/project/httpx2/): the HTTP client behind the Streamable HTTP and SSE *client* transports, with server-sent events support built in.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/), and [`python-multipart`](https://pypi.org/project/python-multipart/): the HTTP *server* transports.
* [`jsonschema`](https://pypi.org/project/jsonschema/): validates a tool's structured output against its declared output schema.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): OAuth token handling for authorization.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): just the lightweight API, so the SDK's tracing middleware costs nothing unless you install an OpenTelemetry SDK and exporter yourself.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) and [`typing-inspection`](https://pypi.org/project/typing-inspection/): modern typing features on Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): Windows only, used for `stdio` subprocess management.

## Optional extras

* `mcp[cli]` adds [`typer`](https://typer.tiangolo.com/) and [`python-dotenv`](https://pypi.org/project/python-dotenv/) for the `mcp` command-line tool (`mcp dev`, `mcp run`, `mcp install`). You'll want this during development; you may not need it in a deployed server.
* `mcp[rich]` adds [`rich`](https://rich.readthedocs.io/) for nicer server logs.
