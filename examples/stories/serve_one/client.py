"""Drive `handle_one` directly to assert the raw result-dict shape, then over the wire."""

from mcp import types
from mcp.client import Client
from mcp.shared.version import LATEST_MODERN_VERSION
from stories._harness import connect_from_args, run_client
from stories.serve_one.server_lowlevel import build_server as build_lowlevel
from stories.serve_one.server_lowlevel import handle_one


async def scenario(client: Client) -> None:
    # ── direct: the namesake recipe — Connection.from_envelope + serve_one → raw result dict.
    # The entry enters lifespan once and threads it to every per-request handle_one().
    server = build_lowlevel()
    params = {
        "name": "add",
        "arguments": {"a": 2, "b": 3},
        "_meta": {
            types.PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
            types.CLIENT_INFO_META_KEY: {"name": "serve-one-probe", "version": "0.0.0"},
            types.CLIENT_CAPABILITIES_META_KEY: {},
        },
    }
    async with server.lifespan(server) as lifespan_state:
        raw = await handle_one(server, "tools/call", params, lifespan_state=lifespan_state)
    assert raw["structuredContent"] == {"result": 5}, raw
    assert raw["content"][0] == {"type": "text", "text": "5"}, raw

    # ── over the wire: the loop-mode driver behind the connected client.
    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["add"]

    result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}, result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
