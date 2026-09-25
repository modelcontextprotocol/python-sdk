# MCP Client

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

`mcp-client` provides the official Python SDK's clients, transports, OAuth support,
and shared protocol machinery without installing Starlette, Uvicorn,
`sse-starlette`, or `python-multipart`. It depends on the matching `mcp-types`
release for protocol models.

`mcp_client` exports the high-level client API. Import OAuth support from
`mcp_client.client.auth` and protocol models from `mcp_types`.
The full `mcp` distribution preserves the existing `mcp.client`, `mcp.shared`,
and `mcp.os` import paths as aliases to the same implementation.

Install `mcp` instead if you also build servers, use the CLI, or pass a server
instance to `Client(server)` for in-process testing. It includes the matching
`mcp-client` release and preserves existing imports such as `from mcp import Client`.

See the [client documentation](https://py.sdk.modelcontextprotocol.io/client/)
for usage and the [repository](https://github.com/modelcontextprotocol/python-sdk)
for development instructions.
