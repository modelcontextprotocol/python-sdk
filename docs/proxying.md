# Proxying MCP Transports

The `mcp_proxy()` helper bridges two MCP transports and forwards messages in both directions.

It is useful when you want to put a transport boundary between an MCP client and an upstream MCP server without
rewriting the forwarding loop yourself.

## What It Does

`mcp_proxy()` takes two transport pairs:

- a transport facing the downstream client
- a transport facing the upstream server

While the context manager is active, it:

- forwards `SessionMessage` objects from client to server
- forwards `SessionMessage` objects from server to client
- sends transport exceptions to an optional `on_error` callback
- closes the paired write side when the corresponding read side stops

## What It Does Not Do

`mcp_proxy()` is a transport relay, not a full proxy server.

It does not add:

- authentication
- authorization
- request or response rewriting
- routing across multiple upstream servers
- retries or buffering policies
- metrics or tracing by default

If you need those behaviors, build them around the helper.

## Weather Service Example

This example proxies a small weather service. The upstream service is defined with `MCPServer` and exposed over
streamable HTTP. The proxy bridges a downstream transport to that upstream transport.

- `get_weather(city)` for a structured weather snapshot
- `get_weather_alerts(region)` for active alerts

The client talks only to the downstream side of the proxy.

```python
import anyio
import uvicorn

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.proxy import mcp_proxy
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams


app = MCPServer("Weather Service")


@app.tool()
def get_weather(city: str) -> dict[str, str | float]:
    return {
        "city": city,
        "temperature_c": 22.5,
        "condition": "partly cloudy",
        "wind_speed_kmh": 12.3,
    }


@app.tool()
def get_weather_alerts(region: str) -> dict[str, object]:
    return {
        "region": region,
        "alerts": [{"severity": "medium", "title": "Heat advisory"}],
    }


async def main() -> None:
    starlette_app = app.streamable_http_app(streamable_http_path="/mcp")
    config = uvicorn.Config(starlette_app, host="127.0.0.1", port=8765, log_level="warning")
    upstream_server = uvicorn.Server(config)

    async with (
        create_client_server_memory_streams() as (client_streams, proxy_client_streams),
        streamable_http_client("http://127.0.0.1:8765/mcp") as proxy_server_streams,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(upstream_server.serve)

        async with mcp_proxy(
            proxy_client_streams,
            proxy_server_streams,
        ):
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                await session.initialize()
                weather = await session.call_tool("get_weather", {"city": "London"})
                alerts = await session.call_tool("get_weather_alerts", {"region": "California"})

                print(weather.content[0].text)
                print(alerts.content[0].text)

        upstream_server.should_exit = True
        tg.cancel_scope.cancel()


anyio.run(main)
```

## Error Handling

Use `on_error` to observe transport-level exceptions:

```python
async with mcp_proxy(
    downstream_transport,
    upstream_transport,
    on_error=handle_transport_error,
):
    ...
```

`on_error` is keyword-only. It may be either:

- an async callable
- a sync callable, which will run in a worker thread

Exceptions raised by `on_error` are swallowed. Transport exceptions still terminate the proxy instead of being silently
consumed.

## When To Use It

`mcp_proxy()` is a good fit when you are:

- exposing an upstream MCP server through a different transport boundary
- inserting middleware-like behavior between two MCP transports
- building a local relay for testing or development
- experimenting with transport adapters

If all you need is to test a server directly, prefer [`Client`](testing.md), which already provides an in-memory
transport for that use case.
