# Installation

The Python SDK is on PyPI as [`mcp`](https://pypi.org/project/mcp/). It requires **Python 3.10+**.

These docs describe **v2**, which is in alpha, so the version pin is not optional yet:

=== "uv"

    ```bash
    uv add "mcp[cli]==2.0.0a3"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]==2.0.0a3"
    ```

!!! warning "Why the pin"
    Installers never select a pre-release unless you name one, so an unpinned `uv add "mcp[cli]"`
    gives you the latest **v1.x** release, which these docs do not describe. Check the
    [release history](https://pypi.org/project/mcp/#history) for the newest alpha before you copy
    the line above.

    The same applies to one-off commands: `uv run --with "mcp==2.0.0a3" ...`, not `uv run --with mcp ...`.

    If your *package* depends on `mcp`, add a `<2` upper bound (for example `mcp>=1.27,<2`) before
    the stable v2 lands so the major version bump doesn't surprise you.

## What gets installed

You don't need to know any of this to use the SDK, but if you're wondering what each dependency is for:

* `mcp-types`: every protocol type (requests, results, content blocks) as its own package, versioned in lockstep with the SDK. Every `from mcp_types import ...` in these docs is this package.
* [`anyio`](https://anyio.readthedocs.io/): the async runtime. The whole SDK is written against anyio, so it runs on either `asyncio` or `trio`.
* [`pydantic`](https://docs.pydantic.dev/): what every `mcp_types` model is built on, plus all schema generation and validation.
* [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/): server configuration via `MCP_*` environment variables and `.env` files.
* [`httpx`](https://www.python-httpx.org/) and [`httpx-sse`](https://pypi.org/project/httpx-sse/): the HTTP client behind the Streamable HTTP and SSE *client* transports.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/), and [`python-multipart`](https://pypi.org/project/python-multipart/): the HTTP *server* transports.
* [`jsonschema`](https://pypi.org/project/jsonschema/): validates a tool's structured output against its declared output schema.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): OAuth token handling for authorization.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): just the lightweight API, so the SDK's tracing middleware costs nothing unless you install an OpenTelemetry SDK and exporter yourself.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) and `typing-inspection`: modern typing features on Python 3.10.
* `pywin32`: Windows only, used for `stdio` subprocess management.

## Optional extras

* `mcp[cli]` adds [`typer`](https://typer.tiangolo.com/) and `python-dotenv` for the `mcp` command-line tool (`mcp dev`, `mcp run`, `mcp install`). You'll want this during development; you may not need it in a deployed server.
* `mcp[rich]` adds [`rich`](https://rich.readthedocs.io/) for nicer server logs.
