# Installation

The Python SDK is available on PyPI as [`mcp`](https://pypi.org/project/mcp/) so installation is as simple as:

=== "pip"

    ```bash
    pip install mcp
    ```
=== "uv"

    ```bash
    uv add mcp
    ```

The following dependencies are automatically installed:

- [`httpx`](https://pypi.org/project/httpx/): HTTP client to handle HTTP Streamable and SSE transports.
- [`httpx-sse`](https://pypi.org/project/httpx-sse/): HTTP client to handle SSE transport.
- [`pydantic`](https://pypi.org/project/pydantic/): Types, JSON schema generation, data validation, and [more](https://docs.pydantic.dev/latest/).
- [`starlette`](https://pypi.org/project/starlette/): Web framework used to build the HTTP transport endpoints.
- [`python-multipart`](https://pypi.org/project/python-multipart/): Handle HTTP body parsing.
- [`sse-starlette`](https://pypi.org/project/sse-starlette/): Server-Sent Events for Starlette, used to build the SSE transport endpoint.
- [`pydantic-settings`](https://pypi.org/project/pydantic-settings/): Settings management used in MCPServer.
- [`uvicorn`](https://pypi.org/project/uvicorn/): ASGI server used to run the HTTP transport endpoints.
- [`jsonschema`](https://pypi.org/project/jsonschema/): JSON schema validation.

This package has the following optional groups:

- `cli`: Installs `typer` and `python-dotenv` for the MCP CLI tools.
- `stdio`: Installs [`pywin32`](https://pypi.org/project/pywin32/) on Windows for Job Object based subprocess cleanup in `mcp.client.stdio`.

Server-only Windows installs can use the base `mcp` package (or `mcp[cli]`) without pulling in `pywin32`. Add the `stdio` extra only if you want the additional Windows stdio cleanup integration.
